"""
AetherOS — Auth Keys & Org Router
Extracted from auth_router.py.

Routes for API key management and org-switcher:
  POST   /auth/api-keys
  GET    /auth/api-keys
  DELETE /auth/api-keys/{key_id}
  GET    /auth/mfa/status
  GET    /auth/my-orgs
  POST   /auth/switch-org
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from aether_os.core.rate_limiter import get_client_ip
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _current_user():
    return Depends(get_current_user)


# ── Pydantic models ────────────────────────────────────────────────────────────

class ApiKeyCreateRequest(BaseModel):
    name: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/api-keys")
async def create_api_key(
    req: ApiKeyCreateRequest,
    request: Request,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Create a new API key for the current organisation."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import APIKey
    from aether_os.gateway.auth import generate_api_key, hash_api_key

    org_id = user.get("org_id")
    raw_key = generate_api_key()
    hashed = hash_api_key(raw_key)

    session_factory = get_session_factory()
    async with session_factory() as session:
        api_key = APIKey(
            id=str(uuid.uuid4()),
            org_id=org_id,
            key_hash=hashed,
            name=req.name,
        )
        session.add(api_key)
        await session.commit()

        # Audit: api_key_created
        from aether_os.core.audit.ledger import get_ledger
        client_ip = get_client_ip(request)
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=org_id,
            user_id=user.get("user_id", "-"),
            action="api_key_created",
            resource_type="api_key",
            resource_id=api_key.id,
            metadata={"name": req.name},
            ip_address=client_ip,
            user_agent=request.headers.get("User-Agent", "-")
        ))

    return {
        "api_key": raw_key,
        "name": req.name,
        "message": "Store this key safely. It will not be shown again.",
    }


@router.get("/api-keys")
async def list_api_keys(user: Dict[str, Any] = _current_user()) -> list:
    """List all active API keys for the current organisation."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import APIKey
    from sqlalchemy import select

    session_factory = get_session_factory()
    async with session_factory() as session:
        rows = (await session.execute(
            select(APIKey).where(APIKey.org_id == user["org_id"], APIKey.is_active == True)
        )).scalars().all()
    return [
        {"id": k.id, "name": k.name, "created_at": str(k.created_at), "last_used_at": k.last_used_at}
        for k in rows
    ]


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str, request: Request, user: Dict[str, Any] = _current_user()) -> Dict[str, str]:
    """Revoke an API key by ID."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import APIKey

    session_factory = get_session_factory()
    async with session_factory() as session:
        key = await session.get(APIKey, key_id)
        if not key or key.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="API key not found")
        key.is_active = False
        await session.commit()

        # Audit: api_key_revoked
        from aether_os.core.audit.ledger import get_ledger
        client_ip = get_client_ip(request)
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=user["org_id"],
            user_id=user.get("user_id", "-"),
            action="api_key_revoked",
            resource_type="api_key",
            resource_id=key_id,
            ip_address=client_ip,
            user_agent=request.headers.get("User-Agent", "-")
        ))

    return {"status": "revoked"}


@router.get("/mfa/status")
async def mfa_status(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    """Return whether MFA is enabled for the current user."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User as _User
    sf = get_session_factory()
    async with sf() as session:
        u = await session.get(_User, user.get("user_id", user.get("sub", "")))
    return {"enabled": bool(u.mfa_enabled) if u else False}


@router.get("/my-orgs")
async def get_my_orgs(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    """Return all organisations the current user belongs to."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation, User as _User
    sf = get_session_factory()
    async with sf() as session:
        org = await session.get(Organisation, user["org_id"])
        u = await session.get(_User, user.get("user_id", user.get("sub", "")))
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return {
        "current_org_id": org.id,
        "orgs": [
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "plan": org.plan,
                "role": u.role if u else user.get("role", "member"),
                "is_current": True,
            }
        ],
    }


@router.post("/switch-org")
async def switch_org(req: Dict[str, Any], user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    """Switch the authenticated user's active organisation and issue new tokens.

    Currently users belong to exactly one org; this endpoint validates the
    request and reissues tokens for the requested org (supports future
    multi-org membership via the UserOrg join table when added).
    """
    org_id = req.get("org_id", "")
    if not org_id:
        raise HTTPException(status_code=422, detail="org_id is required")

    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation, User as _User
    sf = get_session_factory()
    async with sf() as session:
        u = await session.get(_User, user.get("user_id", user.get("sub", "")))
        org = await session.get(Organisation, org_id)

    if not u or not org:
        raise HTTPException(status_code=404, detail="Organisation not found or access denied")

    # Verify the user actually belongs to this org
    if str(u.org_id) != str(org_id):
        raise HTTPException(status_code=403, detail="You do not belong to that organisation")

    from aether_os.gateway.auth import create_access_token, create_refresh_token
    claims = {
        "sub": u.email,
        "user_id": u.id,
        "org_id": org.id,
        "org_slug": org.slug,
        "role": u.role,
        "plan": org.plan,
    }
    return {
        "access_token": create_access_token(claims),
        "refresh_token": create_refresh_token(claims),
        "token_type": "bearer",
        "org_id": org.id,
        "org_slug": org.slug,
    }
