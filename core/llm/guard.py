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
import os

from aether_os.core.llm.plans import PLATFORM_ORG, PLATFORM_PLAN
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

    cap = token_cap = None
    if org_id:
        policy = await controls.org_policy(org_id)
        if policy is None or policy.deleted:
            raise LLMUnavailable(f"Cannot determine plan for org {org_id}")
        if policy.disabled:
            raise LLMUnavailable("LLM calls are disabled for this organisation")
        # The organisation's own plan is authoritative. A caller-supplied plan (pipeline_run falls back to "trial" when
        # the run row has none) made the cap come from the org (pro, $200) while the token limit came from the
        # caller's plan (trial, 500k): p01 intent_verification was refused at 845,087/500,000 tokens.
        if plan and plan != policy.plan:
            logger.warning("LLM call for org %s passed plan %r but the organisation is on %r: using %r",
                           org_id, plan, policy.plan, policy.plan)
        plan, cap, token_cap = policy.plan, policy.effective_cap_usd(), policy.token_cap
    else:
        # Platform-owned call (no tenant): charged to the platform budget (PLATFORM_ORG row, plan "platform",
        # monthly cap PLATFORM_LLM_MONTHLY_CAP_USD or the plan default), so a runaway platform job stops too.
        org_id, plan = PLATFORM_ORG, PLATFORM_PLAN
        raw_cap = os.environ.get("PLATFORM_LLM_MONTHLY_CAP_USD", "").strip()
        try:
            cap = float(raw_cap) if raw_cap else None
        except ValueError:
            raise LLMUnavailable("PLATFORM_LLM_MONTHLY_CAP_USD is not a number") from None
    if not plan:
        raise LLMUnavailable(f"Cannot determine plan for org {org_id}")
    # Only an org with its own token cap passes one: every other call keeps the plan default inside check_budget.
    extra = {"token_cap": token_cap} if token_cap is not None else {}
    try:
        allowed, reason, hint = await get_budget_manager().check_budget(
            org_id, plan, projected_cost_usd=worst_case_cost_usd(prompt, system, max_tokens), cap_usd=cap, **extra)
    except Exception as exc:
        raise LLMUnavailable(f"Token budget check unavailable: {exc}") from exc
    if not allowed:
        raise LLMUnavailable(f"Token budget exceeded: {reason}")
    return Admission(plan, hint, reasons)
