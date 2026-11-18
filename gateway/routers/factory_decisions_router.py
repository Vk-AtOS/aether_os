"""
AetherOS — org-wide pipeline decisions inbox

  GET /factory/decisions?status=pending&limit=50&offset=0

Decisions (spec approvals, phase gates) are per run; this lists them across every run of the caller's
organisation so an approver does not have to open each run. Deciding stays on the per-run routes
(run_spec_router), which check the member role; the inbox links to the run and calls them.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from aether_os.core.decisions.decision_engine import get_decision_engine
from aether_os.gateway.dependencies import get_current_user

router = APIRouter(tags=["decisions"])
_STATUSES = {"pending", "approved", "denied", "timeout"}
MAX_LIMIT = 100


@router.get("/factory/decisions")
async def list_org_decisions(
    status: Optional[str] = "pending",
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Decisions of the caller's organisation only (org comes from the token, never the request)."""
    if status and status not in _STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(_STATUSES)}")
    rows = await get_decision_engine().list_for_org(user["org_id"], status=status, limit=limit, offset=offset)
    return {"decisions": [d.to_dict() for d in rows], "limit": limit, "offset": offset}
