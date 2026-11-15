"""Everything that must be true BEFORE a model call is made (D6, KAN-116).

    admission = await admit(org_id, plan, prompt, system, max_tokens, enforce_local)

Order: global kill switch -> org exists/not deleted/not disabled -> plan known -> monthly token
and USD allowance (hard stop at 100%, alert at 80%) -> sensitivity classification. Anything that
cannot be determined (database down, unknown plan, missing org) refuses the call: unknown spend
is not zero spend. Local-only calls (Ollama on our own host) cost nothing and send nothing out,
so they skip the spend checks but still honour the kill switches.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from aether_os.core.errors import LLMUnavailable
from aether_os.core.llm import controls
from aether_os.core.llm.budget import _COST_PER_INPUT_TOKEN, _COST_PER_OUTPUT_TOKEN, get_budget_manager
from aether_os.core.llm.plans import PLATFORM_PLAN
from aether_os.core.llm.sensitivity import classify

logger = logging.getLogger(__name__)
# Most expensive configured rate: the worst case for a call whose model is not chosen yet.
_MAX_IN = max(_COST_PER_INPUT_TOKEN.values())
_MAX_OUT = max(_COST_PER_OUTPUT_TOKEN.values())


@dataclass(frozen=True)
class Admission:
    plan: str
    model_hint: str                 # "sonnet" | "haiku" (budget nearly used)
    sensitive_reasons: List[str]    # non-empty: no community/free provider may see this prompt


def worst_case_cost_usd(prompt: str, system: Optional[str], max_tokens: int) -> float:
    in_tokens = (len(prompt) + len(system or "")) // 4
    return in_tokens * _MAX_IN + max_tokens * _MAX_OUT


async def admit(org_id: Optional[str], plan: Optional[str], prompt: str, system: Optional[str],
                max_tokens: int, enforce_local: bool = False) -> Admission:
    if await controls.global_kill_active():
        raise LLMUnavailable("LLM calls are disabled by the platform kill switch")
    reasons = classify(prompt, system or "")
    if reasons:
        logger.info("LLM call classified sensitive (%s): restricted to approved providers", ",".join(reasons))
    if enforce_local:
        return Admission(plan or "local", "sonnet", reasons)

    cap = None
    if org_id:
        policy = await controls.org_policy(org_id)
        if policy is None or policy.deleted:
            raise LLMUnavailable(f"Cannot determine plan for org {org_id}")
        if policy.disabled:
            raise LLMUnavailable("LLM calls are disabled for this organisation")
        plan, cap = plan or policy.plan, policy.cap_usd
    else:
        # Platform-owned call (no tenant): nothing to charge a per-org cap to; the kill switches above
        # and the provider's own billing limits govern it.
        return Admission(PLATFORM_PLAN, "sonnet", reasons)
    if not plan:
        raise LLMUnavailable(f"Cannot determine plan for org {org_id}")
    try:
        allowed, reason, hint = await get_budget_manager().check_budget(
            org_id, plan, projected_cost_usd=worst_case_cost_usd(prompt, system, max_tokens), cap_usd=cap)
    except Exception as exc:
        raise LLMUnavailable(f"Token budget check unavailable: {exc}") from exc
    if not allowed:
        raise LLMUnavailable(f"Token budget exceeded: {reason}")
    return Admission(plan, hint, reasons)
