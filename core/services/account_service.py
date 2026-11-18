"""
AetherOS — Account Service
Business logic extracted from gateway/routers/account_router.py.
All direct DB queries live here; the router delegates to these functions.
"""
from __future__ import annotations
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import select, func, or_, update as _saup
from sqlalchemy.ext.asyncio import AsyncSession
from aether_os.core.models import CodebaseProfile
from aether_os.core.models import Organisation
from aether_os.core.models import User
from aether_os.core.models import Run
from aether_os.core.models import APIKey
from datetime import datetime as _dt
from sqlalchemy import update
import os
logger = logging.getLogger(__name__)
async def get_org_usage(sess: AsyncSession, org_id: str) -> Dict[str, Any]:
    """Return usage and plan info for the given org."""
    stmt = select(Organisation).where(Organisation.id == org_id)
    org = (await sess.execute(stmt)).scalar_one_or_none()
    if not org:
        return None  # caller raises 404
    return {
        "org_name": org.name,
        "org_slug": org.slug,
        "plan": org.plan,
        "runs_used": org.trial_runs_used,
        "runs_limit": org.trial_runs_limit if org.plan == "trial" else None,
        "runs_remaining": max(0, org.trial_runs_limit - org.trial_runs_used)
        if org.plan == "trial"
        else None,
        "country": os.environ.get("ORG_COUNTRY", "IN"),
        "org_country": os.environ.get("ORG_COUNTRY", "IN"),
    }
async def get_org_storage(sess: AsyncSession, org_id: str) -> Optional[Dict[str, Any]]:
    """Return storage usage for the given org, or None if not found."""
    org = (await sess.execute(
        select(Organisation).where(Organisation.id == org_id)
    )).scalar_one_or_none()
    if not org:
        return None
    limit = -1
    if org.plan == "trial":
        limit = 500
    elif org.plan == "pro":
        limit = 10000
    return {
        "used_mb": org.storage_used_mb,
        "limit_mb": limit,
        "percent_used": (org.storage_used_mb / limit * 100) if limit > 0 else 0,
        "plan": org.plan,
    }
async def list_projects(
    sess: AsyncSession, org_id: str
) -> List[Dict[str, Any]]:
    """List all generated projects for the org, grouped by name."""
    rows = (await sess.execute(
        select(
            Run.project_name,
            Run.domain,
            Run.status,
            func.count().label("run_count"),
            func.max(Run.started_at).label("last_run_at"),
            func.max(Run.id).label("run_id"),
        )
        .where(Run.org_id == org_id)
        .group_by(Run.project_name, Run.domain, Run.status)
        .order_by(func.max(Run.started_at).desc())
    )).all()
    return [
        {
            "project_name": r.project_name,
            "domain": r.domain,
            "run_count": r.run_count,
            "last_run_at": r.last_run_at,
            "status": r.status,
            "run_id": r.run_id,
        }
        for r in rows
    ]
async def search_projects(
    sess: AsyncSession, org_id: str, q: str, limit: int = 50
) -> List[Dict[str, Any]]:
    """Search projects by name or requirement text (ilike)."""
    pattern = f"%{q}%"
    rows = (await sess.execute(
        select(
            Run.project_name,
            Run.domain,
            Run.status,
            func.count().label("run_count"),
            func.max(Run.started_at).label("last_run_at"),
            func.max(Run.id).label("run_id"),
        )
        .where(
            Run.org_id == org_id,
            or_(
                Run.project_name.ilike(pattern),
                Run.command.ilike(pattern),
                Run.raw_input.ilike(pattern)
                if hasattr(Run, "raw_input")
                else Run.command.ilike(pattern),
            ),
        )
        .group_by(Run.project_name, Run.domain, Run.status)
        .order_by(func.max(Run.started_at).desc())
        .limit(limit)
    )).all()
    return [
        {
            "project_name": r.project_name or f"run-{r.run_id[:8]}",
            "domain": r.domain or "general",
            "run_count": r.run_count,
            "last_run_at": r.last_run_at,
            "status": r.status,
            "run_id": r.run_id,
        }
        for r in rows
    ]
async def get_user_for_export(
    sess: AsyncSession, user_id: str, org_id: str, run_limit: int = 500
) -> tuple:
    """Return (db_user, runs_list) for GDPR data export."""
    db_user = await sess.get(User, user_id)
    runs = (await sess.execute(
        select(Run)
        .where(Run.org_id == org_id, Run.user_id == user_id)  # this user's runs, not the org's
        .order_by(Run.started_at.desc())
        .limit(run_limit)
    )).scalars().all()
    return db_user, list(runs)
async def anonymise_and_deactivate_user(
    sess: AsyncSession, user_id: str, org_id: str
) -> None:
    """
    GDPR erasure: anonymise and soft-delete a user. API keys belong to the organisation
    (the table has no user column), so they are revoked only when this was the org's last
    active user. Caller must commit.
    """
    db_user = await sess.get(User, user_id)
    if not db_user or db_user.org_id != org_id:
        return  # caller raises 404
    db_user.email = f"deleted_{user_id[:8]}@deleted.invalid"
    db_user.password_hash = "DELETED"
    db_user.is_active = False
    db_user.deleted_at = _dt.utcnow()
    db_user.user_preferences = None
    others = (await sess.execute(
        select(func.count()).select_from(User).where(
            User.org_id == org_id, User.id != user_id, User.is_active.is_(True), User.deleted_at.is_(None))
    )).scalar() or 0
    if others == 0:
        await sess.execute(
            _saup(APIKey).where(APIKey.org_id == org_id).values(is_active=False)
        )
async def get_user_preferences(
    sess: AsyncSession, user_id: str
) -> Optional[Dict[str, Any]]:
    """Return parsed user_preferences JSON for the user, or None if not found."""
    u = (await sess.execute(
        select(User).where(User.id == user_id)
    )).scalar_one_or_none()
    if not u:
        return None
    return json.loads(u.user_preferences) if u.user_preferences else None
async def update_user_preferences(
    sess: AsyncSession, user_id: str, updates: Dict[str, Any], defaults: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Merge updates into existing user preferences and persist.
    Returns the merged preferences. Caller must commit.
    """
    u = (await sess.execute(
        select(User).where(User.id == user_id)
    )).scalar_one_or_none()
    existing = (
        json.loads(u.user_preferences) if u and u.user_preferences else dict(defaults)
    )
    existing.update(updates)
    await sess.execute(
        update(User)
        .where(User.id == user_id)
        .values(user_preferences=json.dumps(existing))
    )
    return existing
async def update_org_settings(
    sess: AsyncSession,
    org_id: str,
    payload: Dict[str, Any],
) -> None:
    """Apply allowed org-level settings. Caller must commit."""
    stmt = update(Organisation).where(Organisation.id == org_id).values(payload)
    await sess.execute(stmt)
async def get_org_settings(sess: AsyncSession, org_id: str) -> Optional[Dict[str, Any]]:
    """Return org-level settings fields, or None if org not found."""
    org = await sess.get(Organisation, org_id)
    if not org:
        return None
    return {
        "autonomous_mode": org.autonomous_mode,
        "data_region": org.data_region,
        "plan": org.plan,
        "name": org.name,
    }
async def soft_delete_org(
    sess: AsyncSession, org_id: str
) -> bool:
    """
    Soft-delete the org and anonymise all its users.
    Returns False if org is not found or already deleted. Caller must commit.
    """
    org = await sess.get(Organisation, org_id)
    if not org or org.is_deleted:
        return False
    org.is_deleted = True
    org.deleted_at = _dt.utcnow()
    users = (await sess.execute(
        select(User).where(User.org_id == org_id)
    )).scalars().all()
    for u in users:
        u.is_active = False
        u.email = f"deleted_{u.id[:8]}@deleted.invalid"
        u.password_hash = "DELETED"
        u.deleted_at = org.deleted_at
    return True
async def restore_org(
    sess: AsyncSession, org_id: str
) -> bool:
    """
    Restore a soft-deleted org (flag only — user data may already be anonymised).
    Returns False if org not found or not deleted. Caller must commit.
    """
    org = await sess.get(Organisation, org_id)
    if not org or not org.is_deleted:
        return False
    org.is_deleted = False
    org.deleted_at = None
    return True
async def save_codebase_profile(
    sess: AsyncSession,
    org_id: str,
    repo_url: str,
    repo_name: str,
    detected_stack: Dict[str, Any],
    file_tree: Dict[str, Any],
    summary: str,
) -> Any:
    """Persist a CodebaseProfile and return the refreshed object."""
    profile = CodebaseProfile(
        org_id=org_id,
        repo_url=repo_url,
        repo_name=repo_name,
        detected_stack=detected_stack,
        file_tree=file_tree,
        summary=summary,
    )
    sess.add(profile)
    await sess.commit()
    await sess.refresh(profile)
    return profile
async def list_codebase_profiles(
    sess: AsyncSession, org_id: str, limit: int = 50
) -> List[Any]:
    """Return all codebase profiles for the org, newest first."""
    rows = (await sess.execute(
        select(CodebaseProfile)
        .where(CodebaseProfile.org_id == org_id)
        .order_by(CodebaseProfile.created_at.desc())
        .limit(limit)
    )).scalars().all()
    return list(rows)