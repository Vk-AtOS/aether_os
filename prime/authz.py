"""
Prime — deterministic authorisation core.

`authorize` is a pure function: (action, now, delegations) -> Decision. No I/O,
no model calls. It fails closed: anything it cannot positively justify from a
live delegation is refused or handed to a human.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum, IntEnum
from typing import Any, Dict, FrozenSet, Iterable, Literal, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

PRIME = "prime"
MAX_DELEGATION_DURATION = timedelta(days=30)

# ponytail: one currency, no FX. Amounts in any other currency can never match a
# delegation limit, so they go to the deputy. Add a rates table when needed.
CURRENCY = "INR"
PAYMENT_CEILING = Decimal("500000")

# Action types Prime understands. True = monetary (needs amount + a delegation limit).
ACTION_TYPES: Dict[str, bool] = {
    "leave.approve": False,
    "deploy.staging": False,
    "invoice.approve": True,
    "expense.approve": True,
    "payment.execute": True,
}

# Refused whatever any delegation says. Payments above PAYMENT_CEILING are the
# one NEVER rule that depends on the amount; it is enforced in authorize().
NEVER: FrozenSet[str] = frozenset({
    "person.terminate",
    "person.hire",
    "pay.change",
    "contract.sign",
    "delegation.modify",
    "autonomy.change",
    "ledger.delete",
    "ledger.alter",
    "security.disable",
})


class AutonomyLevel(IntEnum):
    OBSERVE = 0             # observe only
    RECOMMEND = 1           # recommend
    ACT_WITH_APPROVAL = 2   # act with prior approval
    ACT_THEN_NOTIFY = 3     # act, then notify
    ACT_SILENTLY = 4        # act within delegation without notice


class Outcome(str, Enum):
    EXECUTE = "EXECUTE"
    EXECUTE_AND_NOTIFY = "EXECUTE_AND_NOTIFY"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"
    RECOMMEND_ONLY = "RECOMMEND_ONLY"
    ROUTE_TO_DEPUTY = "ROUTE_TO_DEPUTY"
    REFUSE = "REFUSE"


_LEVEL_OUTCOME = {
    AutonomyLevel.OBSERVE: Outcome.REFUSE,
    AutonomyLevel.RECOMMEND: Outcome.RECOMMEND_ONLY,
    AutonomyLevel.ACT_WITH_APPROVAL: Outcome.NEEDS_APPROVAL,
    AutonomyLevel.ACT_THEN_NOTIFY: Outcome.EXECUTE_AND_NOTIFY,
    AutonomyLevel.ACT_SILENTLY: Outcome.EXECUTE,
}


class Limits(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_amount: Decimal = Field(gt=0)
    currency: str


class Delegation(BaseModel):
    """A time-limited grant from one human (grantor) to Prime acting for them."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    grantor: str = Field(min_length=1)
    grantee: Literal["prime"] = PRIME
    scope: FrozenSet[str] = Field(min_length=1)
    limits: Optional[Limits] = None
    autonomy: AutonomyLevel
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    deputy: str = Field(min_length=1)
    revoked_at: Optional[AwareDatetime] = None
    revoked_by: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "Delegation":
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        if self.valid_until - self.valid_from > MAX_DELEGATION_DURATION:
            raise ValueError(
                f"delegation may last at most {MAX_DELEGATION_DURATION.days} days")
        if self.deputy in (self.grantor, PRIME):
            raise ValueError("deputy must be a human other than the grantor")
        return self

    def revoke(self, by: str, now: datetime) -> "Delegation":
        return self.model_copy(update={"revoked_at": now, "revoked_by": by})


class Action(BaseModel):
    """Something Prime is asked to do on behalf of an absent person."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    on_behalf_of: str                 # the grantor Prime would be acting for
    requested_by: str                 # who or what asked (model, user, system)
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Outcome
    reason: str
    delegation_id: Optional[str] = None
    deputy: Optional[str] = None      # set when outcome is ROUTE_TO_DEPUTY


def _refuse(reason: str, delegation: Optional[Delegation] = None) -> Decision:
    return Decision(outcome=Outcome.REFUSE, reason=reason,
                    delegation_id=delegation.id if delegation else None)


def _to_deputy(reason: str, d: Delegation) -> Decision:
    return Decision(outcome=Outcome.ROUTE_TO_DEPUTY, delegation_id=d.id, deputy=d.deputy,
                    reason=f"{reason}; routed to deputy {d.deputy}")


def _dead_reason(d: Delegation, now: datetime) -> str:
    """Why a delegation confers no authority at `now`; '' if it is live."""
    if d.revoked_at is not None:
        return f"delegation {d.id} was revoked"
    if now < d.valid_from:
        return f"delegation {d.id} is not valid until {d.valid_from.isoformat()}"
    if now >= d.valid_until:  # valid_until itself is already outside the window
        return f"delegation {d.id} expired at {d.valid_until.isoformat()}"
    return ""


def authorize(action: Action, now: datetime,
              delegations: Iterable[Delegation] = ()) -> Decision:
    """Decide what Prime may do with `action` at `now`, given the stored delegations.

    Pure and fail-closed. EXECUTE / EXECUTE_AND_NOTIFY are reached only through a
    live, unrevoked, in-scope delegation from `action.on_behalf_of` whose limits
    cover the action.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    if action.type in NEVER:
        return _refuse(f"'{action.type}' is on the NEVER list; no delegation can allow it")
    if action.type not in ACTION_TYPES:
        return _refuse(f"unknown action type '{action.type}'")

    monetary = ACTION_TYPES[action.type]
    if monetary:
        if action.amount is None or action.currency is None:
            return _refuse(f"'{action.type}' needs an amount and a currency")
        if action.amount <= 0:
            return _refuse("amount must be positive")
        if action.amount > PAYMENT_CEILING:
            return _refuse(f"amount {action.amount} is above the hard ceiling "
                           f"{PAYMENT_CEILING} {CURRENCY}; no delegation can allow it")

    mine = sorted((d for d in delegations
                   if d.grantor == action.on_behalf_of and d.grantee == PRIME),
                  key=lambda d: (d.autonomy, d.id))
    if not mine:
        return _refuse(f"no delegation from {action.on_behalf_of}")

    live = [d for d in mine if not _dead_reason(d, now)]
    if not live:
        return _refuse(_dead_reason(mine[0], now), mine[0])

    in_scope = [d for d in live if action.type in d.scope]
    if not in_scope:
        return _to_deputy(f"'{action.type}' is outside the delegated scope", live[0])

    # ponytail: with several matching delegations the lowest autonomy level wins
    # (sorted above). Revoke the narrower one if the broader one should apply.
    d = in_scope[0]

    if monetary:
        if d.limits is None:
            return _to_deputy(f"delegation {d.id} sets no amount limit", d)
        if action.currency != CURRENCY or d.limits.currency != CURRENCY:
            return _to_deputy(f"only {CURRENCY} amounts can be checked "
                              f"(action {action.currency}, limit {d.limits.currency})", d)
        if action.amount > d.limits.max_amount:
            return _to_deputy(f"amount {action.amount} exceeds the delegated limit "
                              f"{d.limits.max_amount} {CURRENCY}", d)

    outcome = _LEVEL_OUTCOME[d.autonomy]
    return Decision(
        outcome=outcome, delegation_id=d.id,
        reason=f"'{action.type}' is within delegation {d.id} from {d.grantor} "
               f"at autonomy level {int(d.autonomy)} ({d.autonomy.name})",
    )
