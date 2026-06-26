"""
AetherOS — Account Settings Router
=====================================
Organisation-level settings and lifecycle management.

Routes
------
  POST /account/settings
  GET  /account/settings
  DELETE /org
  POST /org/restore

Split from account_router.py to keep that file under 400 lines.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["account"])


def _current_user():
    return Depends(get_current_user)


@router.post("/account/settings")
async def update_settings(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Update account settings (e.g. decision_mode, autonomous_mode)."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    from sqlalchemy import update

    # Allowlist: only non-privileged fields may be updated by org members (FIX-006)
    _ALLOWED = {"decision_mode", "autonomous_mode", "notification_prefs", "org_name", "data_region"}
    payload = {k: v for k, v in req.items() if k in _ALLOWED}
    if not payload:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = update(Organisation).where(Organisation.id == user["org_id"]).values(payload)
        await session.execute(stmt)
        await session.commit()
        return {"status": "ok", "updated": list(payload.keys())}


@router.get("/account/settings")
async def get_org_settings(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return org-level settings (autonomous_mode, data_region, etc.)."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    session_factory = get_session_factory()
    async with session_factory() as session:
        org = await session.get(Organisation, user["org_id"])
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return {
        "autonomous_mode": org.autonomous_mode,
        "data_region": org.data_region,
        "plan": org.plan,
        "name": org.name,
    }


@router.delete("/org")
async def delete_organisation(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, str]:
    """Soft-delete the current organisation and deactivate all its users (owner only)."""
    if user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only org owners can delete the organisation")
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation, User
    from sqlalchemy import select
    from datetime import datetime as _dt

    org_id = user["org_id"]
    session_factory = get_session_factory()
    async with session_factory() as session:
        org = await session.get(Organisation, org_id)
        if not org or org.is_deleted:
            raise HTTPException(status_code=404, detail="Organisation not found")

        # Soft delete org
        org.is_deleted = True
        org.deleted_at = _dt.utcnow()

        # Deactivate and anonymise all users in this org
        users = (await session.execute(select(User).where(User.org_id == org_id))).scalars().all()
        for u in users:
            u.is_active = False
            u.email = f"deleted_{u.id[:8]}@deleted.invalid"
            u.password_hash = "DELETED"
            u.deleted_at = org.deleted_at

        await session.commit()

    # Audit: org.deleted
    from aether_os.core.audit.ledger import get_ledger
    asyncio.create_task(get_ledger().async_log_audit_event(
        org_id=org_id,
        user_id=user.get("user_id", "-"),
        action="org.deleted",
        resource_type="organisation",
        resource_id=org_id,
    ))

    return {"message": "Organisation scheduled for deletion. All users deactivated."}


@router.get("/orgs/me/usage")
async def get_org_usage_endpoint(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return current org usage stats for billing and settings panels."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.services.account_service import get_org_usage

    org_id = user.get("org_id", "")
    if not org_id:
        return {"api_calls": 0, "storage_gb": 0, "runs_this_month": 0, "cost_usd": 0.0}
    try:
        async with get_session_factory()() as session:
            result = await get_org_usage(session, org_id)
        if result is None:
            return {"api_calls": 0, "storage_gb": 0, "runs_this_month": 0, "cost_usd": 0.0}
        # Augment the account_service result with billing-panel fields
        return {
            **result,
            "api_calls": 0,
            "storage_gb": 0,
            "runs_this_month": result.get("runs_used", 0),
            "cost_usd": 0.0,
        }
    except Exception as exc:
        logger.warning("get_org_usage_endpoint: DB query failed for org=%s: %s", org_id, exc)
        return {"api_calls": 0, "storage_gb": 0, "runs_this_month": 0, "cost_usd": 0.0}


@router.post("/org/restore")
async def restore_organisation(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, str]:
    """Restore a soft-deleted organisation (owner only)."""
    if user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only org owners can restore the organisation")

    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation

    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        org = await session.get(Organisation, org_id)
        if not org or not org.is_deleted:
            return {"message": "Organisation is not deleted"}

        org.is_deleted = False
        org.deleted_at = None

        await session.commit()

    return {"message": "Organisation restored. Note: Users may need manual email restoration."}
