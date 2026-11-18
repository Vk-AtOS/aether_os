"""
AetherOS — notification preferences

  GET /notifications/preferences          the caller's effective settings per event
  PUT /notifications/preferences          the caller's own override {event, in_app?, email?}
  PUT /notifications/preferences/org      the organisation default (owner/admin; a user's own setting wins)
  GET /notifications/quiet-hours          the caller's effective quiet hours (own, else the organisation's) or null
  PUT /notifications/quiet-hours          {start: "22:00", end: "07:00", tz: "Asia/Kolkata"}; start == end clears them
  PUT /notifications/quiet-hours/org      the organisation default (owner/admin)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


class QuietUpdate(BaseModel):
    start: str          # "HH:MM", local time of tz
    end: str
    tz: str = "UTC"


def _minute(text: str) -> int:
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", text or "")
    if not m:
        raise HTTPException(status_code=422, detail="times are HH:MM (24 hour)")
    return int(m[1]) * 60 + int(m[2])


def _quiet_args(req: QuietUpdate) -> tuple:
    try:
        ZoneInfo(req.tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise HTTPException(status_code=422, detail="tz must be an IANA time zone such as Asia/Kolkata") from None
    return _minute(req.start), _minute(req.end), req.tz


def _quiet_view(q: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not q:
        return {"quiet_hours": None, "exempt_events": sorted(prefs.QUIET_EXEMPT)}
    f = lambda m: f"{m // 60:02d}:{m % 60:02d}"  # noqa: E731
    return {"quiet_hours": {"start": f(q["start_minute"]), "end": f(q["end_minute"]), "tz": q["tz"], "source": q["source"]},
            "exempt_events": sorted(prefs.QUIET_EXEMPT)}


@router.get("/notifications/quiet-hours")
async def get_quiet_hours(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return _quiet_view(await prefs.get_quiet(user["org_id"], user.get("user_id")))


@router.put("/notifications/quiet-hours")
async def put_quiet_hours(req: QuietUpdate, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if not user.get("user_id"):
        raise HTTPException(status_code=403, detail="Quiet hours belong to a signed-in user")
    await prefs.set_quiet(user["org_id"], user["user_id"], *_quiet_args(req))
    return _quiet_view(await prefs.get_quiet(user["org_id"], user["user_id"]))


@router.put("/notifications/quiet-hours/org")
async def put_org_quiet_hours(req: QuietUpdate, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only org owners/admins may change the organisation default")
    await prefs.set_quiet(user["org_id"], prefs.ORG_DEFAULT, *_quiet_args(req))
    return _quiet_view(await prefs.get_quiet(user["org_id"], user.get("user_id")))
