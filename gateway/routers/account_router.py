"""
AetherOS — Account Router
GET /account/usage
GET /account/storage
GET /account/projects
GET /account/projects/search
GET /account/data-export
DELETE /account
GET /account/preferences
PUT /account/preferences

Settings and org lifecycle routes live in account_settings_router.py.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from aether_os.gateway.auth_refresh import revoke_user_sessions
from aether_os.gateway.dependencies import get_current_user
from aether_os.core.services.account_service import (
    get_org_usage,
    get_org_storage,
    list_projects as svc_list_projects,
    search_projects as svc_search_projects,
    anonymise_and_deactivate_user,
    get_user_preferences,
    update_user_preferences,
)

router = APIRouter(tags=["account"])


def _current_user():
    return Depends(get_current_user)


@router.get("/account/usage")
async def get_usage(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get current usage and limits for the organisation."""
    from aether_os.core.db import get_session_factory

    org_id = user.get("org_id")
    async with get_session_factory()() as session:
        result = await get_org_usage(session, org_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Organisation not found")
        return result


@router.get("/account/storage")
async def get_account_storage(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    from aether_os.core.db import get_session_factory

    async with get_session_factory()() as session:
        result = await get_org_storage(session, user["org_id"])
        if result is None:
            raise HTTPException(status_code=404)
        return result


@router.get("/account/projects")
async def list_projects(user: Dict[str, Any] = _current_user()) -> List[Dict[str, Any]]:
    """List all generated projects for the org."""
    from aether_os.core.db import get_session_factory

    async with get_session_factory()() as session:
        return await svc_list_projects(session, user["org_id"])


@router.get("/account/projects/search")
async def search_projects(q: str, user: Dict[str, Any] = _current_user()) -> List[Dict[str, Any]]:
    """Search projects by name or requirement text."""
    from aether_os.core.db import get_session_factory

    async with get_session_factory()() as session:
        return await svc_search_projects(session, user["org_id"], q)


@router.get("/account/data-export")
async def data_export(user: Dict[str, Any] = _current_user()):
    """GDPR portability: return all user data as a downloadable JSON file."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.audit.ledger import get_ledger
    from fastapi.responses import StreamingResponse
    import json as _json

    user_id = user.get("user_id", "")
    org_id = user.get("org_id", "")

    from aether_os.core.services.account_service import get_user_for_export
    async with get_session_factory()() as session:
        db_user, runs = await get_user_for_export(session, user_id, org_id)

    audit = await get_ledger().async_get_audit_logs(org_id=org_id, page=1, limit=500)
    export = {
        "export_version": "1.0",
        "exported_at": time.time(),
        "user": {
            "id": user_id,
            "email": db_user.email if db_user else None,
            "role": db_user.role if db_user else None,
            "created_at": str(db_user.created_at) if db_user else None,
            "consent_at": str(db_user.consent_at) if db_user and db_user.consent_at else None,
        },
        "runs": [
            {"id": r.id, "project_name": r.project_name, "status": r.status,
             "domain": r.domain, "started_at": r.started_at, "cost": r.cost}
            for r in runs
        ],
        "audit_logs": audit.get("logs", []),
    }
    payload = _json.dumps(export, indent=2, default=str).encode()
    return StreamingResponse(
        iter([payload]),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="aetheros-data-export.json"'},
    )


@router.delete("/account")
async def delete_account(user: Dict[str, Any] = _current_user()) -> Dict[str, str]:
    """GDPR erasure: anonymise and soft-delete the calling user's account."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.audit.ledger import get_ledger

    user_id = user.get("user_id", "")
    org_id = user.get("org_id", "")

    # End every session the user holds (all access and refresh tokens) first. If
    # that cannot be done (Redis down) this raises 503 and nothing is deleted, so
    # the user can retry — never a deleted account with live tokens.
    await revoke_user_sessions(user_id)

    async with get_session_factory()() as session:
        await anonymise_and_deactivate_user(session, user_id, org_id)
        await session.commit()

    await get_ledger().async_log_audit_event(
        org_id=org_id, user_id=user_id, action="account.deleted",
        resource_type="user", resource_id=user_id, metadata={}, ip_address="self",
    )
    return {"message": "Account deleted"}


@router.get("/account/preferences")
async def get_preferences(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get user preferences."""
    from aether_os.core.db import get_session_factory

    async with get_session_factory()() as session:
        result = await get_user_preferences(session, user["user_id"])
        if result is None:
            raise HTTPException(status_code=404)
        return result if result else dict(_DEFAULT_PREFERENCES)


_DEFAULT_PREFERENCES = {
    "default_tab_on_run_complete": "artifacts",
    "pinned_phases": [],
    "collapsed_phases": [],
    "decision_notification_style": "panel",
    "live_feed_visible_by_default": True,
    "default_domain": "general",
    "default_start_mode": "single",
    "dashboard_theme": "default",
    "sidebar_collapsed": False,
    "compact_phase_list": False,
    "show_confidence_scores": True,
    "workspace_name": "My Workspace",
}


@router.put("/account/preferences")
async def update_preferences(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Update user preferences."""
    from aether_os.core.db import get_session_factory

    async with get_session_factory()() as session:
        result = await update_user_preferences(session, user["user_id"], req, _DEFAULT_PREFERENCES)
        await session.commit()
    return result


# ── Settings and org lifecycle routes live in account_settings_router.py ───────
# ── Codebase import and profile routes live in account_codebase_router.py ─────
