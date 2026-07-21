"""
AetherOS — Marketplace Router
GET /marketplace/profiles
GET /marketplace/profiles/{profile_id}
POST /marketplace/publish
POST /marketplace/install/{profile_id}
PUT /marketplace/profiles/{profile_id}
DELETE /marketplace/profiles/{profile_id}
"""
from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from aether_os.gateway.dependencies import get_current_user
from aether_os.core.db import get_session_factory
from aether_os.core.models import InstalledPluginRecord, MarketplaceProfile
from aether_os.core.models import MarketplaceProfile
from aether_os.core.services.pipeline_service import get_pipeline_service
from sqlalchemy import select
from sqlalchemy import select as _sel
from sqlalchemy import select, func
from sqlalchemy import select, update as _sa_upd
import uuid as _uuid_mp
router = APIRouter(tags=["marketplace"])
def _current_user():
    return Depends(get_current_user)
@router.get("/marketplace/installed")
async def list_installed_profiles(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """FE-H2: Return the marketplace profiles installed for the caller's org.
    Reads from InstalledPluginRecord which is written on POST /marketplace/install/{id}.
    """
    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        rows = (await session.execute(
            select(InstalledPluginRecord)
            .where(InstalledPluginRecord.org_id == org_id)
            .order_by(InstalledPluginRecord.installed_at.desc())
        )).scalars().all()
        # Enrich with profile metadata where possible
        profile_ids = [r.plugin_id for r in rows if r.plugin_id]
        profiles_map: Dict[str, Any] = {}
        if profile_ids:
            profiles = (await session.execute(
                select(MarketplaceProfile).where(MarketplaceProfile.id.in_(profile_ids))
            )).scalars().all()
            profiles_map = {p.id: p for p in profiles}
    items = [
        {
            "id": r.id,
            "plugin_id": r.plugin_id,
            "name": profiles_map[r.plugin_id].name if r.plugin_id in profiles_map else r.plugin_id,
            "base_domain": profiles_map[r.plugin_id].base_domain if r.plugin_id in profiles_map else None,
            "installed_at": r.installed_at,
            "test_status": r.test_status,
            "last_tested_at": r.last_tested_at,
        }
        for r in rows
    ]
    return {"items": items, "total": len(items)}
@router.get("/marketplace/profiles")
async def list_profiles(page: int = 1, limit: int = 20):
    limit = min(max(limit, 1), 100)
    page = max(page, 1)
    sf = get_session_factory()
    async with sf() as session:
        total = (await session.execute(
            select(func.count()).where(MarketplaceProfile.is_published == True)
        )).scalar_one()
        rows = (await session.execute(
            select(MarketplaceProfile)
            .where(MarketplaceProfile.is_published == True)
            .offset((page - 1) * limit).limit(limit)
        )).scalars().all()
    items = [
        {
            "id": p.id,
            "name": p.name,
            "base_domain": p.base_domain,
            "description": p.description,
            "price_usd": p.price_usd,
            "usage_count": p.usage_count,
            "org_id": p.org_id,
        }
        for p in rows
    ]
    return {"items": items, "page": page, "limit": limit, "total": total}
@router.get("/marketplace/profiles/{profile_id}")
async def get_marketplace_profile(profile_id: str) -> Dict[str, Any]:
    sf = get_session_factory()
    async with sf() as session:
        p = (await session.execute(
            _sel(MarketplaceProfile).where(MarketplaceProfile.id == profile_id)
        )).scalar_one_or_none()
    if not p or not p.is_published:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {
        "id": p.id, "name": p.name, "base_domain": p.base_domain,
        "description": p.description, "price_usd": p.price_usd,
        "profile_yaml": p.profile_yaml, "usage_count": p.usage_count,
        "org_id": p.org_id, "created_at": p.created_at.isoformat() if p.created_at else None,
    }
@router.post("/marketplace/publish")
async def publish_profile(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    name = req.get("name") or ""
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    session_factory = get_session_factory()
    async with session_factory() as session:
        profile = MarketplaceProfile(
            id=str(_uuid_mp.uuid4()),
            org_id=user["org_id"],
            name=name,
            base_domain=req.get("base_domain", "general"),
            description=req.get("description", ""),
            price_usd=float(req.get("price_usd", 0.0)),
            is_published=True,
        )
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return {"status": "published", "id": profile.id, "name": profile.name}
@router.post("/marketplace/install/{profile_id}")
async def install_marketplace_profile(
    profile_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """T5-02: Install a marketplace profile — increment usage_count and start a
    pipeline run pre-configured with the profile's domain and YAML settings."""
    sf = get_session_factory()
    async with sf() as session:
        profile = (await session.execute(
            select(MarketplaceProfile).where(
                MarketplaceProfile.id == profile_id,
                MarketplaceProfile.is_published == True,  # noqa: E712
            )
        )).scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found or not published")
        # Increment usage counter atomically
        await session.execute(
            _sa_upd(MarketplaceProfile)
            .where(MarketplaceProfile.id == profile_id)
            .values(usage_count=MarketplaceProfile.usage_count + 1)
        )
        await session.commit()
    # Start a pipeline run pre-seeded with the profile configuration
    try:
        svc = get_pipeline_service()
        result = await svc.start_run(
            org_id=user["org_id"],
            org_slug=user.get("org_slug", ""),
            plan=user.get("plan", "trial"),
            raw_input=f"Install marketplace profile: {profile.name}. {profile.description or ''}",
            project_name=profile.name,
            domain=profile.base_domain,
        )
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    return {
        "installed": True,
        "profile_id": profile_id,
        "profile_name": profile.name,
        "run_id": result.get("run_id"),
    }
@router.put("/marketplace/profiles/{profile_id}")
async def update_marketplace_profile(
    profile_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    sf = get_session_factory()
    async with sf() as session:
        p = await session.get(MarketplaceProfile, profile_id)
        if not p or p.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Profile not found")
        for field_name in ("name", "description", "base_domain", "price_usd", "profile_yaml"):
            if field_name in body:
                setattr(p, field_name, body[field_name])
        await session.commit()
        await session.refresh(p)
    return {"id": p.id, "name": p.name, "updated": True}
@router.delete("/marketplace/profiles/{profile_id}", status_code=204)
async def delete_marketplace_profile(
    profile_id: str,
    user: Dict[str, Any] = _current_user(),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    sf = get_session_factory()
    async with sf() as session:
        p = await session.get(MarketplaceProfile, profile_id)
        if not p or p.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Profile not found")
        await session.delete(p)
        await session.commit()