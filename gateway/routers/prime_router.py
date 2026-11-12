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
    ACTION_TYPES, NEVER,
    Action, AutonomyLevel, Delegation, DelegationRepository, Limits, PrimeService,
)
from aether_os.prime.authz import (
    CURRENCY, HARD_MAX_DELEGATION_DURATION, HARD_PAYMENT_CEILING, Amount, Currency,
)
from aether_os.prime.executors import DEFAULT_EXECUTOR, REGISTRY
from aether_os.prime import ledger_view
from aether_os.prime.limits import OrgLimits, get_limits, set_limits

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/prime", tags=["prime"])

_repo = DelegationRepository()
_service = PrimeService(_repo)

# ponytail: activity is a linear scan of the org's prime.* entries. Fine for a single company's
# volume; add an indexed (subject, seq) column when the chain passes this size.
_ACTIVITY_SCAN_LIMIT = 20_000
_ACTIVITY_LIMIT = 200


class DelegationIn(BaseModel):
    scope: List[str] = Field(min_length=1)
    autonomy: AutonomyLevel
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    deputy: str = Field(min_length=1, max_length=255)
    max_amount: Optional[Amount] = None


class LimitsIn(BaseModel):
    # No upper bound here: set_limits() refuses above the hard ceiling with a clear 400.
    payment_ceiling: Decimal = Field(gt=0, decimal_places=2, allow_inf_nan=False)
    max_delegation_days: int = Field(ge=1)


class ActionIn(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    amount: Optional[Amount] = None
    currency: Optional[Currency] = None


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
        "id": d.id, "grantor": d.grantor, "scope": sorted(d.scope), "autonomy": int(d.autonomy),
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
        "executors": sorted(REGISTRY), "default_executor": DEFAULT_EXECUTOR,
        "currency": CURRENCY, **_limits_out(await get_limits(user.get("org_id"))),
    }


def _limits_out(limits: OrgLimits) -> Dict[str, Any]:
    return {"payment_ceiling": str(limits.payment_ceiling),
            "max_delegation_days": limits.max_delegation_days}


@router.get("/limits")
async def read_limits(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """This organisation's Prime limits and the bounds no setting can pass."""
    return {**_limits_out(await get_limits(user.get("org_id"))), "currency": CURRENCY,
            "hard_payment_ceiling": str(HARD_PAYMENT_CEILING),
            "hard_max_delegation_days": HARD_MAX_DELEGATION_DURATION.days,
            "can_edit": user.get("role") in ("owner", "admin")}


@router.put("/limits")
async def write_limits(
    body: LimitsIn, user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Change the organisation's limits. Organisation admins only; ledgered."""
    uid = _uid(user)
    if user.get("role") not in ("owner", "admin") or not user.get("org_id"):
        raise HTTPException(status_code=403, detail="Only an organisation admin can change Prime limits")
    try:
        new = await set_limits(user["org_id"], uid, body.payment_ceiling, body.max_delegation_days)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _limits_out(new)


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
            valid_from=body.valid_from, valid_until=body.valid_until,
            # Lower-cased so the deputy's sign-in email matches it in the inbox.
            deputy=body.deputy.strip().lower(),
            limits=Limits(max_amount=body.max_amount, currency=CURRENCY) if body.max_amount else None,
        )
        await _repo.add(d, org_id=user.get("org_id"))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.errors()[0]["msg"]) from e
    except PermissionError as e:  # the grantor's role does not hold what they grant
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:  # the organisation's own limits
        raise HTTPException(status_code=400, detail=str(e)) from e
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
    await _repo.revoke(delegation_id, by=uid, now=datetime.now(timezone.utc),
                       org_id=user.get("org_id"))
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
    decision = await _service.decide(action, user.get("org_id"))
    return {"action_id": action.id, **decision.model_dump(mode="json")}


def _org(user: Dict[str, Any]) -> str:
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=403, detail="No organisation on this sign-in")
    return str(org_id)


@router.get("/activity")
async def activity(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Ledger entries about the caller's own delegations and Prime decisions, newest first.
    Read through the caller's organisation only (prime.ledger_view), never other orgs' chains."""
    uid, org_id = _uid(user), _org(user)
    mine: List[Dict[str, Any]] = []
    scanned, cursor = 0, None
    while len(mine) < _ACTIVITY_LIMIT and scanned < _ACTIVITY_SCAN_LIMIT:
        page = await ledger_view.browse(org_id, action_prefix="prime.", before_seq=cursor, limit=200)
        for e in page["entries"]:
            p = e["payload"]
            if uid in (e["actor"], p.get("on_behalf_of"), p.get("grantor")):
                mine.append({k: e[k] for k in ("seq", "timestamp", "actor", "action", "payload", "entry_hash")})
        scanned += len(page["entries"])
        cursor = page["next_before"]
        if cursor is None:
            break
    return {"entries": mine[:_ACTIVITY_LIMIT]}


@router.get("/ledger/verify")
async def verify_ledger(full: bool = False, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Verify the caller's own organisation chain (incrementally from its newest signed
    checkpoint). `full=true` rescans every entry: organisation admins only. Returns only
    counts and status, never entries."""
    org_id = _org(user)
    if full and user.get("role") not in ("owner", "admin", "superadmin"):
        raise HTTPException(status_code=403, detail="A full verification is for organisation admins")
    result = await audit_chain.verify(org_id, full=full)
    return {"ok": result.ok, "entries_checked": result.entries_checked,
            "broken_seq": result.broken_seq, "reason": result.reason,
            "chain_id": result.chain_id, "head_seq": result.head_seq,
            "checkpoint_seq": result.checkpoint_seq, "full": full}
