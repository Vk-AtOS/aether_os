"""
AetherOS — organisation onboarding

  GET  /onboarding           steps (derived from real data) and whether the org hid the banner
  POST /onboarding/dismiss   hide it for the whole organisation (owner/admin: it is org-wide state)
  POST /onboarding/dpa       accept the data processing agreement for the organisation (owner/admin; stored with user and time)
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aether_os.core import onboarding
from aether_os.gateway.dependencies import get_current_user

router = APIRouter(tags=["onboarding"])


@router.get("/onboarding")
async def get_onboarding(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return await onboarding.progress(user["org_id"])


@router.post("/onboarding/dismiss")
async def dismiss_onboarding(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") not in ("owner", "admin") or not user.get("user_id"):
        raise HTTPException(status_code=403, detail="Only org owners/admins may hide the onboarding for the organisation")
    await onboarding.dismiss(user["org_id"], user["user_id"])
    return {"dismissed": True}


class DpaIn(BaseModel):
    version: str


@router.post("/onboarding/dpa")
async def accept_dpa(body: DpaIn, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") not in ("owner", "admin") or not user.get("user_id"):
        raise HTTPException(status_code=403, detail="Only org owners/admins may accept the DPA for the organisation")
    if body.version != onboarding.DPA_VERSION:    # a stale page must not accept a text it did not show
        raise HTTPException(status_code=409, detail=f"The current DPA is version {onboarding.DPA_VERSION}")
    await onboarding.accept_dpa(user["org_id"], user["user_id"])
    return {"accepted": True, "version": onboarding.DPA_VERSION}
