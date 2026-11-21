"""
AetherOS — model provider status for the Settings page (KAN-18)
GET /settings/provider-status — per provider: key on file (never the key), endpoint host, AHM health and breaker state.

Adding and rotating a key is POST /settings/api-keys; the one-call test is POST /settings/test-provider.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from aether_os.core.db import get_session_factory
from aether_os.core.services.provider_status import provider_status
from aether_os.gateway.dependencies import get_current_user

router = APIRouter(tags=["settings"])

_ADMIN_ROLES = ("owner", "admin", "superadmin")


@router.get("/settings/provider-status")
async def get_provider_status(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only org owners/admins may view provider status.")
    async with get_session_factory()() as session:
        return {"providers": await provider_status(session, user.get("org_id", ""))}
