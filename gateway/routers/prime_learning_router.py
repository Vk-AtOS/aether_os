"""Prime API — what Prime has learned (KAN-229): the organisation's learned items and whether they help.

Organisation-level data only (build and approval learnings, pseudonymised; no per-person view). Every signed-in person
of the organisation may read it. Retiring or restoring an item changes what goes into every prompt of the
organisation, so the handler itself requires an owner or admin (the role gate lets viewers POST under /prime/, so
hiding the buttons alone would not be enough).
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from aether_os.gateway.dependencies import get_current_user
from aether_os.prime.learning import adapters, loop, metrics

router = APIRouter(prefix="/prime/learning", tags=["prime-learning"])
_ADMIN = ("owner", "admin")


def _org(user: Dict[str, Any]) -> str:
    if not user.get("org_id"):
        raise HTTPException(status_code=403, detail="No organisation on this sign-in")
    return str(user["org_id"])


def _kind(kind: str) -> str:
    if kind not in loop.KINDS:
        raise HTTPException(status_code=404, detail="Unknown kind")
    return kind


@router.get("/items")
async def items(kind: List[str] = Query(default=[], max_length=3),
                user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Per kind (correction, golden, fix): this organisation's learned items with usage, help rate and retirement."""
    kinds = [_kind(k) for k in kind] or list(loop.KINDS)
    return {"kinds": await adapters.learned_items(_org(user), kinds), "retire_after": loop.RETIRE_AFTER}


@router.get("/metrics")
async def learning_metrics(weeks: int = Query(default=12, ge=1, le=metrics.MAX_WEEKS),
                           user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Per week: help rate per kind, build first-pass rate and correction rate."""
    return await metrics.weekly(_org(user), weeks)


async def _set(kind: str, item_id: str, retired: bool, user: Dict[str, Any]) -> Dict[str, Any]:
    if user.get("role") not in _ADMIN:
        raise HTTPException(status_code=403, detail="Only an organisation owner or admin can do this")
    org = _org(user)
    if not await adapters.item_exists(org, _kind(kind), item_id):
        raise HTTPException(status_code=404, detail="Learned item not found")
    return await loop.set_retired(org, kind, item_id, retired, str(user.get("user_id") or user.get("sub") or "admin"))


@router.post("/items/{kind}/{item_id}/retire")
async def retire(kind: str, item_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Stop putting this item into prompts (owner or admin)."""
    return await _set(kind, item_id, True, user)


@router.post("/items/{kind}/{item_id}/restore")
async def restore(kind: str, item_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Put a retired item back into prompts with a fresh failure count (owner or admin)."""
    return await _set(kind, item_id, False, user)
