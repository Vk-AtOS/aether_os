"""Prime API — read-only ledger browser, one organisation at a time.

Organisation admins see every entry of their organisation. Everyone else sees only
the entries they made themselves. Each organisation has its own chain; an entry's
"previous" is the entry before it in that same chain. Verifying one organisation's
chain and its signed checkpoints is POST /prime/ledger/anchor/verify.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers.prime_router import _uid
from aether_os.prime import ledger_view

router = APIRouter(prefix="/prime/ledger", tags=["prime"])


def _scope(user: Dict[str, Any]) -> tuple:
    """(org id, actor the caller is limited to or None for the whole organisation)."""
    uid = _uid(user)
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=403, detail="No organisation on this sign-in")
    return str(org_id), None if user.get("role") in ("owner", "admin") else uid


def _epoch(dt: Optional[datetime]) -> Optional[float]:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


@router.get("/entries")
async def list_entries(
    actor: Optional[str] = Query(default=None, max_length=255),
    event: Optional[str] = Query(default=None, max_length=255,
                                 description="Event type or a prefix of it, e.g. prime.approval"),
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    before: Optional[int] = Query(default=None, ge=1, description="Cursor: next_before of the previous page"),
    limit: int = Query(default=50, ge=1, le=200),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    org_id, only_actor = _scope(user)
    if only_actor and actor not in (None, only_actor):
        return {"entries": [], "next_before": None, "whole_org": False}
    page = await ledger_view.browse(
        org_id, actor=only_actor or actor, action_prefix=event,
        since=_epoch(since), until=_epoch(until), before_seq=before, limit=limit)
    return {**page, "whole_org": only_actor is None}


@router.get("/entries/{seq}")
async def get_entry(seq: int, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """One entry, the hash of the entry before it, and whether the link holds."""
    org_id, only_actor = _scope(user)
    found = await ledger_view.entry(org_id, seq)
    if found is None or (only_actor and found["actor"] != only_actor):
        raise HTTPException(status_code=404, detail="Entry not found")
    return found
