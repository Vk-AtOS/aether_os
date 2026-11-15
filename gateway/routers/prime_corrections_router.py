"""Prime API — correction memory (KAN-24) and the eval sets built from it (KAN-25).

Signed-in people and organisation API keys (a system such as Velaris asking before an agent
proposes an action) read corrections of their OWN organisation only. Marking a correction a
good example and exporting eval sets change or expose organisation-wide data, so they need
an owner or admin (D7); the API key may export, for the eval script.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from aether_os.core.db import get_session_factory
from aether_os.gateway.dependencies import get_current_user
from aether_os.prime import corrections
from aether_os.prime.models import PrimeCorrection

router = APIRouter(prefix="/prime/corrections", tags=["prime-corrections"])
_ADMIN = ("owner", "admin")


def _org(user: Dict[str, Any]) -> str:
    if not user.get("org_id"):
        raise HTTPException(status_code=403, detail="No organisation on this sign-in")
    return str(user["org_id"])


def _admin(user: Dict[str, Any]) -> str:
    if user.get("role") not in _ADMIN:
        raise HTTPException(status_code=403, detail="Only an organisation owner or admin can do this")
    return _org(user)


class OutcomeIn(BaseModel):
    ids: List[str] = Field(max_length=corrections.TOP_K_MAX)
    changed: bool


class GoodIn(BaseModel):
    good: bool


@router.get("/relevant")
async def relevant(
    agent: str = Query(min_length=1, max_length=128), action_type: str = Query(min_length=1, max_length=64),
    q: str = Query(default="", max_length=2000), k: int = Query(default=3, ge=1, le=corrections.TOP_K_MAX),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """The corrections to show an agent before it proposes this action, and the prompt block."""
    found = await corrections.relevant(_org(user), agent, action_type, q, k)
    return {"corrections": found, "prompt_block": corrections.prompt_block(found)}


@router.post("/outcome")
async def outcome(body: OutcomeIn, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, int]:
    """Say whether the retrieved corrections changed what the agent proposed."""
    return {"updated": await corrections.record_outcome(_org(user), body.ids, body.changed)}


@router.put("/{correction_id}/good-example")
async def mark_good_example(correction_id: str, body: GoodIn,
                            user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    org = _admin(user)
    async with get_session_factory()() as session:
        n = (await session.execute(update(PrimeCorrection).where(
            PrimeCorrection.id == correction_id, PrimeCorrection.org_id == org)
            .values(good_example=body.good))).rowcount
        await session.commit()
    if not n:
        raise HTTPException(status_code=404, detail="Correction not found")
    return {"id": correction_id, "good_example": body.good}


@router.get("/eval-set")
async def eval_set(
    agent: Optional[str] = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Good examples as test cases: input, expected corrected output. Edits only (a rejection
    has no corrected output). Pseudonymised exactly as stored."""
    if user.get("role") not in (*_ADMIN, "api"):
        raise HTTPException(status_code=403, detail="Only an organisation owner or admin can do this")
    org = _org(user)
    conds = [PrimeCorrection.org_id == org, PrimeCorrection.good_example.is_(True),
             PrimeCorrection.corrected.notlike('{"rejected":%')]
    if agent:
        conds.append(PrimeCorrection.agent == agent)
    async with get_session_factory()() as session:
        rows = (await session.execute(select(PrimeCorrection).where(*conds)
                                      .order_by(PrimeCorrection.created_at, PrimeCorrection.id)
                                      .limit(limit).offset(offset))).scalars().all()
    return {"cases": [{"id": r.id, "agent": r.agent, "action_type": r.action_type,
                       "input": r.input_summary, "proposed": r.proposed, "expected": r.corrected,
                       "created_at": r.created_at.isoformat()} for r in rows],
            "limit": limit, "offset": offset}
