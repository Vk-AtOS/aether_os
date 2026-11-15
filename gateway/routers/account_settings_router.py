"""
AetherOS — Account Settings Router
=====================================
Organisation-level settings and lifecycle management.

Routes
------
  POST /account/settings
  GET  /account/settings
  DELETE /org

Split from account_router.py to keep that file under 400 lines.
"""
from __future__ import annotations

import logging
from datetime import datetime as _dt
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from aether_os.core.audit.deletion import ErasureIncomplete, erase_organisation
from aether_os.core.audit.ledger import get_ledger
from aether_os.core.db import get_session_factory
from aether_os.core.models import Organisation, User
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["account"])
_ALLOWED = {"autonomous_mode", "org_name", "data_region"}


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

    # Org-wide state (autonomous mode skips spec review, data region, org name): admin or owner only (D7).
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only org owners/admins may change organisation settings")
    # Only keys that are real Organisation columns: decision_mode/notification_prefs have no
    # column, so accepting them made the UPDATE fail or silently do nothing. org_name -> name.
    payload = {("name" if k == "org_name" else k): v for k, v in req.items() if k in _ALLOWED}
    if not payload:
        raise HTTPException(status_code=400, detail=f"No valid fields to update; allowed: {sorted(_ALLOWED)}")
    if "autonomous_mode" in payload and not isinstance(payload["autonomous_mode"], bool):
        raise HTTPException(status_code=422, detail="autonomous_mode must be a boolean")
    if "name" in payload and not (isinstance(payload["name"], str) and 1 <= len(payload["name"].strip()) <= 255):
        raise HTTPException(status_code=422, detail="org_name must be 1-255 characters")
    if "data_region" in payload and not (isinstance(payload["data_region"], str) and 1 <= len(payload["data_region"]) <= 20):
        raise HTTPException(status_code=422, detail="data_region must be 1-20 characters")

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
    """Delete the current organisation (owner only). This cannot be undone: users are anonymised, passwords
    and sign-ins destroyed and ledger personal data erased, and a deleted organisation refuses every token
    (gateway/dependencies.py), so there is no way to call a restore. The dashboard asks for the org name first."""
    if user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only org owners can delete the organisation")
    org_id = user["org_id"]
    async with get_session_factory()() as session:
        org = await session.get(Organisation, org_id)
        if not org or org.is_deleted:
            raise HTTPException(status_code=404, detail="Organisation not found")
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

    # Awaited (not fire-and-forget) and BEFORE the erasure: a late event would otherwise
    # recreate the pepper the erasure deletes.
    by = user.get("user_id", "-")
    await get_ledger().async_log_audit_event(
        org_id=org_id, user_id=by, action="org.deleted",
        resource_type="organisation", resource_id=org_id)
    try:
        await erase_organisation(org_id, by=by)
    except ErasureIncomplete as e:
        # The organisation IS deleted (and refuses sign-ins), so only a platform
        # administrator can finish: erasure is idempotent and recorded as pending.
        raise HTTPException(
            status_code=503,
            detail=f"Organisation deleted, but {e}. A platform administrator can retry: "
                   "POST /prime/ledger/erasure/retry.") from e
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
