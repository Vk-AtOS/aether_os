"""AetherOS — policy rules: may this org, on this plan, with this role, do this action?

Pure and deterministic: evaluate(action, facts) reads nothing and calls nothing,
so every rule is testable with plain values. core.policy.enforce gathers the
facts and ledgers denials; gateway.policy_guard turns a denial into an HTTP error.

Deny by default: an action that is not in ACTIONS is refused, as is an unknown
role or (for anything that starts work) an unknown plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# Rolling window for the runs-per-period quota.
QUOTA_PERIOD_SECONDS = 30 * 86400

# Builds running at once across every org: the host's capacity, not a plan entitlement.
PLATFORM_CONCURRENT_RUNS = 10

# "api" is an organisation API key: it may do what a member may, never admin actions.
ROLE_RANK: Dict[str, int] = {"viewer": 0, "member": 1, "api": 1, "admin": 2, "owner": 3, "superadmin": 4}


@dataclass(frozen=True)
class Entitlement:
    runs_per_period: Optional[int]  # None = no cap in the rolling window
    concurrent_runs: int
    seats: Optional[int] = None     # active users in the org; None = no cap


# trial: the org's own lifetime allowance (trial_runs_limit) is the cap, not the window.
# pro / enterprise are sold as "unlimited runs"; 3 at once is the platform's per-org ceiling.
# Seat numbers are defaults for the owner to review; enterprise is uncapped.
PLAN_ENTITLEMENTS: Dict[str, Entitlement] = {
    "free": Entitlement(runs_per_period=3, concurrent_runs=1, seats=1),
    "trial": Entitlement(runs_per_period=None, concurrent_runs=3, seats=5),
    "starter": Entitlement(runs_per_period=30, concurrent_runs=2, seats=5),
    "pro": Entitlement(runs_per_period=None, concurrent_runs=3, seats=25),
    "enterprise": Entitlement(runs_per_period=None, concurrent_runs=3, seats=None),
}


@dataclass(frozen=True)
class ActionRule:
    min_role: str
    new_run: bool = False       # consumes run quota (trial allowance, runs per period)
    occupies_slot: bool = False  # needs a free concurrent-run slot
    adds_seat: bool = False      # adds an active user: needs a free seat


ACTIONS: Dict[str, ActionRule] = {
    "run.start": ActionRule("member", new_run=True, occupies_slot=True),
    "run.restart": ActionRule("member", occupies_slot=True),
    "run.clarify": ActionRule("member"),
    "billing.change_plan": ActionRule("admin"),
    "portal.token.issue": ActionRule("admin"),
    "portal.token.list": ActionRule("admin"),
    "portal.token.revoke": ActionRule("admin"),
    "portal.approval.list": ActionRule("member"),
    "plugin.manage": ActionRule("admin"),
    "user.add": ActionRule("admin", adds_seat=True),
    "provider.test": ActionRule("admin"),
    "provider.test_platform": ActionRule("superadmin"),
}


@dataclass(frozen=True)
class Facts:
    """What is true about the caller and the org right now. Defaults are the denying values."""
    org_exists: bool = False
    org_deleted: bool = False
    plan: str = ""
    role: str = ""
    active_runs: int = 0
    runs_in_period: int = 0
    trial_runs_used: int = 0
    trial_runs_limit: int = 0
    platform_active_runs: int = 0
    seats_used: int = 0


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str  # machine-readable: "ok" or one of the codes returned below
    detail: Dict[str, Any] = field(default_factory=dict)


def _deny(reason: str, **detail: Any) -> Decision:
    return Decision(False, reason, detail)


def evaluate(action: str, facts: Facts) -> Decision:
    """First failing rule wins; the order is part of the contract (tests pin it)."""
    rule = ACTIONS.get(action)
    if rule is None:
        return _deny("unknown_action")
    if not facts.org_exists:
        return _deny("org_not_found")
    if facts.org_deleted:
        return _deny("org_inactive")
    rank = ROLE_RANK.get(facts.role)
    if rank is None:
        return _deny("role_unknown")
    if rank < ROLE_RANK[rule.min_role]:
        return _deny("role_insufficient", required_role=rule.min_role)
    if not (rule.new_run or rule.occupies_slot or rule.adds_seat):
        return Decision(True, "ok")

    entitlement = PLAN_ENTITLEMENTS.get(facts.plan)
    if entitlement is None:
        return _deny("plan_unknown")
    if rule.adds_seat and entitlement.seats is not None and facts.seats_used >= entitlement.seats:
        return _deny("quota_seats", used=facts.seats_used, limit=entitlement.seats)
    if rule.new_run:
        if facts.plan == "trial" and facts.trial_runs_used >= facts.trial_runs_limit:
            return _deny("trial_limit_reached", used=facts.trial_runs_used, limit=facts.trial_runs_limit)
        cap = entitlement.runs_per_period
        if cap is not None and facts.runs_in_period >= cap:
            return _deny("quota_runs_per_period", used=facts.runs_in_period, limit=cap,
                         period_days=QUOTA_PERIOD_SECONDS // 86400)
    if rule.occupies_slot and facts.active_runs >= entitlement.concurrent_runs:
        return _deny("quota_concurrent_runs", running=facts.active_runs, limit=entitlement.concurrent_runs)
    if rule.occupies_slot and facts.platform_active_runs >= PLATFORM_CONCURRENT_RUNS:
        return _deny("platform_at_capacity", running=facts.platform_active_runs, limit=PLATFORM_CONCURRENT_RUNS)
    return Decision(True, "ok")
