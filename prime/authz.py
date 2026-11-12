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
from typing import Annotated, Any, Dict, FrozenSet, Iterable, Literal, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

PRIME = "prime"
# Defaults. An organisation may change both (prime/limits.py), never past the
# HARD_* bounds below, which no setting can raise.
MAX_DELEGATION_DURATION = timedelta(days=30)
HARD_MAX_DELEGATION_DURATION = timedelta(days=90)

# ponytail: one currency, no FX. Every limit and ceiling is in INR, so an amount in
# any other currency cannot be compared with them and is refused outright (a
# small-unit currency would otherwise slip under an INR ceiling). Add a rates table
# and widen Currency when needed.
CURRENCY = "INR"
Currency = Literal["INR"]
PAYMENT_CEILING = Decimal("500000")
HARD_PAYMENT_CEILING = Decimal("5000000")
_PAISA = Decimal("0.01")
# For every input model that carries money: positive, finite, at most 2 decimal
# places, never above the hard ceiling.
Amount = Annotated[Decimal, Field(gt=0, le=HARD_PAYMENT_CEILING, decimal_places=2,
                                  allow_inf_nan=False)]

# Action types Prime understands. True = monetary (needs amount + a delegation limit).
ACTION_TYPES: Dict[str, bool] = {
    "leave.approve": False,
    "deploy.staging": False,
    "run.spec.approve": False,   # release a build waiting at its specification review gate
    "invoice.approve": True,
    "expense.approve": True,
    "payment.execute": True,
}

# Who holds authority over each action type and each executor, by organisation role
# (core/models.py User.role: owner, admin, member, viewer). A person may delegate only
# what their role holds here; a request is decided and executed only while the person
# it is for, and any human who approves it, still hold it. A role or name missing from
# these tables holds nothing (viewer, API keys, unknown executors).
OWNER_ADMIN: FrozenSet[str] = frozenset({"owner", "admin"})
ANY_MEMBER: FrozenSet[str] = frozenset({"owner", "admin", "member"})
AUTHORITY: Dict[str, FrozenSet[str]] = {
    "leave.approve": OWNER_ADMIN,
    "deploy.staging": ANY_MEMBER,
    "run.spec.approve": ANY_MEMBER,   # the executor checks the run is in the request's org
    "invoice.approve": OWNER_ADMIN,
    "expense.approve": OWNER_ADMIN,
    "payment.execute": OWNER_ADMIN,
}
EXECUTOR_AUTHORITY: Dict[str, FrozenSet[str]] = {
    "dry_run": ANY_MEMBER,            # carries nothing out
    "aetheros.run_gate": ANY_MEMBER,
    "webhook": OWNER_ADMIN,           # org-configured endpoint, signed with the org's secret
}
# Executors whose effect leaves AetherOS. With monetary action types they never run
# on the requester's word alone: a second person must approve.
EXTERNAL_EFFECT: FrozenSet[str] = frozenset({"webhook"})

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

    max_amount: Amount
    currency: Currency


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
        # The organisation's own (lower) limit is enforced where the delegation is
        # stored (DelegationRepository.add); the model enforces the bound nothing can exceed.
        if self.valid_until - self.valid_from > HARD_MAX_DELEGATION_DURATION:
            raise ValueError(
                f"delegation may last at most {HARD_MAX_DELEGATION_DURATION.days} days")
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


def dead_reason(d: Delegation, now: datetime) -> str:
    """Why a delegation confers no authority at `now`; '' if it is live."""
    if d.revoked_at is not None:
        return f"delegation {d.id} was revoked"
    if now < d.valid_from:
        return f"delegation {d.id} is not valid until {d.valid_from.isoformat()}"
    if now >= d.valid_until:  # valid_until itself is already outside the window
        return f"delegation {d.id} expired at {d.valid_until.isoformat()}"
    return ""


def authority_reason(role: Optional[str], action_type: str,
                     executor: Optional[str] = None) -> str:
    """Why a person with `role` does not hold authority over `action_type` (through
    `executor`, if given); '' if they do. role None = not an active person in the org."""
    if role is None:
        return "not an active person in this organisation"
    if role not in AUTHORITY.get(action_type, frozenset()):
        return f"role '{role}' holds no authority over '{action_type}'"
    if executor is not None and role not in EXECUTOR_AUTHORITY.get(executor, frozenset()):
        return f"role '{role}' holds no authority to use executor '{executor}'"
    return ""


def needs_second_person(action_type: str, executor: str) -> bool:
    """Monetary or external-effect: never executed without a person other than the
    requester approving. Unknown action types count as monetary (fail closed)."""
    return ACTION_TYPES.get(action_type, True) or executor in EXTERNAL_EFFECT


def money_reason(action: Action, payment_ceiling: Decimal) -> str:
    """Why the amount/currency of `action` is unacceptable; '' if it is fine.

    Any action that carries an amount is held to this, monetary or not."""
    if action.amount is None and action.currency is None:
        return (f"'{action.type}' needs an amount and a currency"
                if ACTION_TYPES.get(action.type, False) else "")
    if action.amount is None or action.currency is None:
        return "an amount needs a currency, and a currency needs an amount"
    if action.currency != CURRENCY:
        return f"only {CURRENCY} amounts are accepted, not '{action.currency}'"
    amount = action.amount
    if not amount.is_finite() or amount <= 0:
        return "amount must be positive"
    if amount > min(payment_ceiling, HARD_PAYMENT_CEILING):
        return (f"amount {amount} is above the hard ceiling "
                f"{min(payment_ceiling, HARD_PAYMENT_CEILING)} {CURRENCY}; no delegation can allow it")
    if amount.quantize(_PAISA) != amount:   # safe: amount is bounded by the ceiling here
        return "amount may have at most 2 decimal places"
    return ""


def authorize(action: Action, now: datetime,
              delegations: Iterable[Delegation] = (),
              payment_ceiling: Decimal = PAYMENT_CEILING) -> Decision:
    """Decide what Prime may do with `action` at `now`, given the stored delegations.

    Pure and fail-closed. EXECUTE / EXECUTE_AND_NOTIFY are reached only through a
    live, unrevoked, in-scope delegation from `action.on_behalf_of` whose limits
    cover the action.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    payment_ceiling = min(payment_ceiling, HARD_PAYMENT_CEILING)

    if action.type in NEVER:
        return _refuse(f"'{action.type}' is on the NEVER list; no delegation can allow it")
    if action.type not in ACTION_TYPES:
        return _refuse(f"unknown action type '{action.type}'")

    monetary = ACTION_TYPES[action.type]
    bad_money = money_reason(action, payment_ceiling)
    if bad_money:
        return _refuse(bad_money)

    mine = sorted((d for d in delegations
                   if d.grantor == action.on_behalf_of and d.grantee == PRIME),
                  key=lambda d: (d.autonomy, d.id))
    if not mine:
        return _refuse(f"no delegation from {action.on_behalf_of}")

    live = [d for d in mine if not dead_reason(d, now)]
    if not live:
        return _refuse(dead_reason(mine[0], now), mine[0])

    in_scope = [d for d in live if action.type in d.scope]
    if not in_scope:
        return _to_deputy(f"'{action.type}' is outside the delegated scope", live[0])

    # ponytail: with several matching delegations the lowest autonomy level wins
    # (sorted above). Revoke the narrower one if the broader one should apply.
    d = in_scope[0]

    if monetary:
        if d.limits is None:
            return _to_deputy(f"delegation {d.id} sets no amount limit", d)
        if d.limits.currency != CURRENCY:   # unreachable through Limits; kept fail-closed
            return _refuse(f"delegation {d.id} has a limit in '{d.limits.currency}'", d)
        if action.amount > d.limits.max_amount:
            return _to_deputy(f"amount {action.amount} exceeds the delegated limit "
                              f"{d.limits.max_amount} {CURRENCY}", d)

    outcome = _LEVEL_OUTCOME[d.autonomy]
    return Decision(
        outcome=outcome, delegation_id=d.id,
        reason=f"'{action.type}' is within delegation {d.id} from {d.grantor} "
               f"at autonomy level {int(d.autonomy)} ({d.autonomy.name})",
    )
