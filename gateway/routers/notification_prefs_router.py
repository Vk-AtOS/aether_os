"""
AetherOS — notification preferences

  GET /notifications/preferences          the caller's effective settings per event
  PUT /notifications/preferences          the caller's own override {event, in_app?, email?}
  PUT /notifications/preferences/org      the organisation default (owner/admin; a user's own setting wins)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aether_os.core import notification_prefs as prefs
from aether_os.gateway.dependencies import get_current_user

router = APIRouter(tags=["notifications"])


class PrefUpdate(BaseModel):
    event: str
    in_app: Optional[bool] = None
    email: Optional[bool] = None


def _check(req: PrefUpdate) -> None:
    if req.event not in prefs.EVENTS:
        raise HTTPException(status_code=422, detail=f"event must be one of {sorted(prefs.EVENTS)}")
    if req.in_app is None and req.email is None:
        raise HTTPException(status_code=422, detail="set in_app and/or email")


def _view(effective: Dict[str, Dict[str, object]]) -> Dict[str, Any]:
    return {"events": [{"event": e, "label": prefs.EVENTS[e], **v} for e, v in effective.items()]}


@router.get("/notifications/preferences")
async def get_preferences(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return _view(await prefs.effective(user["org_id"], user.get("user_id")))


@router.put("/notifications/preferences")
async def put_preferences(req: PrefUpdate, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    _check(req)
    if not user.get("user_id"):  # an API key has no inbox of its own
        raise HTTPException(status_code=403, detail="Preferences belong to a signed-in user")
    await prefs.set_pref(user["org_id"], user["user_id"], req.event, req.in_app, req.email)
    return _view(await prefs.effective(user["org_id"], user["user_id"]))


@router.put("/notifications/preferences/org")
async def put_org_preferences(req: PrefUpdate, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only org owners/admins may change the organisation default")
    _check(req)
    await prefs.set_pref(user["org_id"], prefs.ORG_DEFAULT, req.event, req.in_app, req.email)
    return _view(await prefs.effective(user["org_id"], user.get("user_id")))
