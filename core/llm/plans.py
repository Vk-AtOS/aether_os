"""Monthly LLM allowance per plan: tokens and USD (D6).

One table for every plan name the product can assign (policy rules, billing and the dashboard
use free/trial/starter/growth/pro/enterprise). A plan that is not here is refused, never given
the trial allowance by accident. The numbers are DEFAULTS that need the owner's review; a single
org can be given its own USD cap (Organisation.llm_monthly_cap_usd).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanLimit:
    tokens: int       # estimated tokens (input + output) per calendar month
    usd: float        # estimated provider spend per calendar month


PLATFORM_ORG = "__platform__"   # the budget row platform-owned calls are charged to (no tenant)
PLATFORM_PLAN = "platform"  # calls with no organisation (platform maintenance, learning jobs)

PLAN_LIMITS = {
    # Token caps leave room for real builds: the heaviest run seen used 172k tokens, so 500k fitted ~3 builds a month (KAN-261).
    "free":       PlanLimit(1_000_000, 2.0),
    "trial":      PlanLimit(3_000_000, 5.0),
    "starter":    PlanLimit(5_000_000, 50.0),
    "growth":     PlanLimit(25_000_000, 250.0),
    "pro":        PlanLimit(25_000_000, 200.0),
    "enterprise": PlanLimit(999_999_999, 2_000.0),
    PLATFORM_PLAN: PlanLimit(999_999_999, 500.0),
}


def token_cap_for(plan: str, org_cap: Optional[int] = None) -> int:
    """The monthly token cap of one organisation: its own override, else LLM_PLAN_TOKEN_CAPS='{"trial": 4000000}',
    else the plan default. Raises KeyError for an unknown plan."""
    if org_cap is not None and org_cap > 0:
        return org_cap
    raw = os.environ.get("LLM_PLAN_TOKEN_CAPS", "").strip()
    if raw:
        try:
            value = int(json.loads(raw).get(plan, 0))
            if value > 0:
                return value
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning("LLM_PLAN_TOKEN_CAPS ignored, not a JSON object of plan -> tokens: %s", e)
    return PLAN_LIMITS[plan].tokens


def limit_for(plan: str) -> PlanLimit:
    """Raises KeyError for an unknown plan: the caller must refuse the call."""
    return PLAN_LIMITS[plan]
