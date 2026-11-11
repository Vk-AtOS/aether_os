"""Prime API — delegations, a decision check, the caller's Prime activity, ledger health.

Every delegation belongs to the signed-in user (grantor = their user id); nobody can
read, create or revoke a delegation for someone else. The router only translates
HTTP to `aether_os.prime`; all decisions are made by `prime.authorize`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from aether_os.core.audit import chain as audit_chain
from aether_os.gateway.dependencies import get_current_user
from aether_os.prime import (
    ACTION_TYPES, MAX_DELEGATION_DURATION, NEVER, PAYMENT_CEILING,
    Action, AutonomyLevel, Delegation, DelegationRepository, Limits, PrimeService,
)
from aether_os.prime.authz import CURRENCY

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/prime", tags=["prime"])

_repo = DelegationRepository()
_service = PrimeService(_repo)

# ponytail: activity is a linear scan of the chain. Fine for a single company's
# volume; add an indexed (subject, seq) column when the chain passes this size.
_ACTIVITY_SCAN_LIMIT = 20_000


class DelegationIn(BaseModel):
    scope: List[str] = Field(min_length=1)
    autonomy: AutonomyLevel
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    deputy: str = Field(min_length=1, max_length=255)
    max_amount: Optional[Decimal] = Field(default=None, gt=0)


class ActionIn(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    amount: Optional[Decimal] = Field(default=None, gt=0)
    currency: Optional[str] = Field(default=None, max_length=3)


def _uid(user: Dict[str, Any]) -> str:
    uid = user.get("user_id")
    if not uid:  # API keys have no person behind them, so they cannot grant or act
        raise HTTPException(status_code=403, detail="Prime needs a signed-in person, not an API key")
    return str(uid)


def _delegation_out(d: Delegation, now: datetime) -> Dict[str, Any]:
    if d.revoked_at:
        state = "revoked"
    elif now < d.valid_from:
        state = "scheduled"
    elif now >= d.valid_until:
        state = "expired"
    else:
        state = "active"
    return {
        "id": d.id, "scope": sorted(d.scope), "autonomy": int(d.autonomy),
        "autonomy_name": d.autonomy.name, "deputy": d.deputy, "state": state,
        "valid_from": d.valid_from.isoformat(), "valid_until": d.valid_until.isoformat(),
        "max_amount": str(d.limits.max_amount) if d.limits else None,
        "currency": d.limits.currency if d.limits else None,
        "revoked_at": d.revoked_at.isoformat() if d.revoked_at else None,
    }


@router.get("/meta")
async def meta(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """What Prime can be asked to do, and what it never does."""
    return {
        "action_types": [{"type": t, "monetary": m} for t, m in sorted(ACTION_TYPES.items())],
        "never": sorted(NEVER),
        "autonomy_levels": [{"level": int(a), "name": a.name} for a in AutonomyLevel],
        "payment_ceiling": str(PAYMENT_CEILING), "currency": CURRENCY,
        "max_delegation_days": MAX_DELEGATION_DURATION.days,
    }


@router.get("/delegations")
async def list_delegations(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    rows = await _repo.for_grantor(_uid(user))
    rows.sort(key=lambda d: d.valid_from, reverse=True)
    return {"delegations": [_delegation_out(d, now) for d in rows]}


@router.post("/delegations", status_code=201)
async def create_delegation(
    body: DelegationIn, user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    unknown = sorted(set(body.scope) - set(ACTION_TYPES))
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown or forbidden action types: {unknown}")
    try:
        d = Delegation(
            grantor=_uid(user), scope=frozenset(body.scope), autonomy=body.autonomy,
            valid_from=body.valid_from, valid_until=body.valid_until, deputy=body.deputy,
            limits=Limits(max_amount=body.max_amount, currency=CURRENCY) if body.max_amount else None,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.errors()[0]["msg"]) from e
    await _repo.add(d)
    return _delegation_out(d, datetime.now(timezone.utc))


@router.post("/delegations/{delegation_id}/revoke")
async def revoke_delegation(
    delegation_id: str, user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    uid = _uid(user)
    # Ownership check: only the grantor's own delegations are visible, so a
    # delegation that belongs to someone else is indistinguishable from a missing one.
    if delegation_id not in {d.id for d in await _repo.for_grantor(uid)}:
        raise HTTPException(status_code=404, detail="Delegation not found")
    await _repo.revoke(delegation_id, by=uid, now=datetime.now(timezone.utc))
    return {"id": delegation_id, "state": "revoked"}


@router.post("/check")
async def check_action(
    body: ActionIn, user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Ask Prime what it would do with this action on the caller's behalf.

    Nothing is executed, but the request and the decision are written to the
    ledger like any other Prime decision.
    """
    uid = _uid(user)
    action = Action(type=body.type, on_behalf_of=uid, requested_by=uid,
                    amount=body.amount, currency=body.currency or (CURRENCY if body.amount else None))
    decision = await _service.decide(action)
    return {"action_id": action.id, **decision.model_dump(mode="json")}


@router.get("/activity")
async def activity(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Ledger entries about the caller's own delegations and Prime decisions, newest first."""
    uid = _uid(user)
    mine: List[Dict[str, Any]] = []
    after = 0
    while after < _ACTIVITY_SCAN_LIMIT:
        batch = await audit_chain.read_entries(limit=1000, after_seq=after)
        if not batch:
            break
        after = batch[-1]["seq"]
        for e in batch:
            p = e["payload"]
            if e["action"].startswith("prime.") and uid in (
                e["actor"], p.get("on_behalf_of"), p.get("grantor")
            ):
                mine.append({"seq": e["seq"], "timestamp": e["timestamp"], "actor": e["actor"],
                             "action": e["action"], "payload": p, "entry_hash": e["entry_hash"]})
    return {"entries": mine[::-1][:200]}


@router.get("/ledger/verify")
async def verify_ledger(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Walk the whole chain. Returns only counts and status, never other tenants' entries."""
    result = await audit_chain.verify()
    return {"ok": result.ok, "entries_checked": result.entries_checked,
            "broken_seq": result.broken_seq, "reason": result.reason}
