"""
AetherOS — operations status (KAN-49)
GET /system/components    — breakers, bulkheads and component health (owner/admin)
GET /system/dead-letters  — jobs that failed repeatedly and were parked (owner/admin: own organisation; superadmin: all)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.models import Run
from aether_os.core.queue.sqs_client import dlq_depth, peek_dlq
from aether_os.core.resilience.health import snapshot
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])

_ADMIN_ROLES = ("owner", "admin", "superadmin")


def _admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.get("/system/components")
async def components(user: Dict[str, Any] = Depends(_admin)) -> Dict[str, Any]:
    return await snapshot()


@router.get("/system/dead-letters")
async def dead_letters(user: Dict[str, Any] = Depends(_admin)) -> Dict[str, Any]:
    """The queue is platform-wide, so an organisation sees only the dead letters of its own runs."""
    items, depth = await asyncio.gather(asyncio.to_thread(peek_dlq, 10), asyncio.to_thread(dlq_depth))
    if user.get("role") != "superadmin":
        ids = [i["run_id"] for i in items if i["run_id"]]
        async with get_session_factory()() as s:
            own = set((await s.execute(
                select(Run.id).where(Run.org_id == user["org_id"], Run.id.in_(ids)))).scalars()) if ids else set()
        items = [i for i in items if i["run_id"] in own]
        depth = len(items)   # the platform-wide count is not an organisation's to see
    return {"depth": depth, "items": items, "note": "a window of at most 10 messages, oldest-visible first"}
