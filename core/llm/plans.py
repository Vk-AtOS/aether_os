"""Monthly LLM allowance per plan: tokens and USD (D6).

One table for every plan name the product can assign (policy rules, billing and the dashboard
use free/trial/starter/growth/pro/enterprise). A plan that is not here is refused, never given
the trial allowance by accident. The numbers are DEFAULTS that need the owner's review; a single
org can be given its own USD cap (Organisation.llm_monthly_cap_usd).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanLimit:
    tokens: int       # estimated tokens (input + output) per calendar month
    usd: float        # estimated provider spend per calendar month


PLATFORM_ORG = "__platform__"   # the budget row platform-owned calls are charged to (no tenant)
PLATFORM_PLAN = "platform"  # calls with no organisation (platform maintenance, learning jobs)

PLAN_LIMITS = {
    "free":       PlanLimit(500_000, 2.0),
    "trial":      PlanLimit(500_000, 5.0),
    "starter":    PlanLimit(5_000_000, 50.0),
    "growth":     PlanLimit(25_000_000, 250.0),
    "pro":        PlanLimit(25_000_000, 250.0),
    "enterprise": PlanLimit(999_999_999, 2_000.0),
    PLATFORM_PLAN: PlanLimit(999_999_999, 500.0),
}


def limit_for(plan: str) -> PlanLimit:
    """Raises KeyError for an unknown plan: the caller must refuse the call."""
    return PLAN_LIMITS[plan]
