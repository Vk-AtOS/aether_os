"""
AetherOS — Notifications Router
GET /notifications
POST /notifications/{notif_id}/read
POST /notifications/read-all
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(tags=["notifications"])


def _current_user():
    from aether_os.gateway.api import get_current_user
    return Depends(get_current_user)


@router.get("/notifications")
async def get_notifications(
    unread_only: bool = False,
    limit: int = 50,
    user: Dict[str, Any] = _current_user(),
):
    from aether_os.core.db import get_session_factory as _gsf_n
    from aether_os.core.models import Notification as _Notif
    from sqlalchemy import select as _sel_n, or_ as _or_n
    async with _gsf_n()() as sess:
        stmt = _sel_n(_Notif).where(
            _or_n(_Notif.user_id == user["user_id"], _Notif.user_id == None)  # noqa: E711
        ).where(_Notif.org_id == user["org_id"]).order_by(_Notif.created_at.desc()).limit(limit)
        if unread_only:
            stmt = stmt.where(_Notif.is_read == False)  # noqa: E712
        rows = (await sess.execute(stmt)).scalars().all()
    unread_count = sum(1 for r in rows if not r.is_read)
    return {
        "items": [
            {
                "id": n.id, "type": n.type, "title": n.title,
                "message": n.message, "link": n.link,
                "is_read": n.is_read, "created_at": n.created_at,
            }
            for n in rows
        ],
        "unread_count": unread_count,
    }


@router.post("/notifications/read-all")
async def mark_all_notifications_read(user: Dict[str, Any] = _current_user()):
    from aether_os.core.db import get_session_factory as _gsf_nr
    from aether_os.core.models import Notification as _NotifR
    from sqlalchemy import update as _upd_n, or_ as _or_nr
    async with _gsf_nr()() as sess:
        await sess.execute(
            _upd_n(_NotifR)
            .where(_NotifR.org_id == user["org_id"])
            .where(_or_nr(_NotifR.user_id == user["user_id"], _NotifR.user_id == None))  # noqa: E711
            .values(is_read=True)
        )
        await sess.commit()
    return {"ok": True}


@router.post("/notifications/{notif_id}/read")
async def mark_notification_read(notif_id: str, user: Dict[str, Any] = _current_user()):
    from aether_os.core.db import get_session_factory as _gsf_nr2
    from aether_os.core.models import Notification as _NotifR2
    async with _gsf_nr2()() as sess:
        n = await sess.get(_NotifR2, notif_id)
        if not n or n.org_id != user["org_id"]:
            raise HTTPException(status_code=404)
        n.is_read = True
        await sess.commit()
    return {"ok": True}
