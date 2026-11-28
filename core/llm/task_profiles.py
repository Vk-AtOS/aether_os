"""One table: task type -> model tier -> max_tokens -> timeout (KAN-211).

Reasoning models (NVIDIA Nemotron) spend part of `max_tokens` on reasoning before the answer, so a limit sized
for the answer alone truncates the reply and the call is wasted. Limits here are sized for reasoning plus answer.

Tiers
  heavy  spec, architecture, business logic, page composition: the large model (OPENROUTER_HEAVY_MODEL).
  light  patches, classification, short reviews, summaries: the small model (OPENROUTER_LIGHT_MODEL).
  none   done by a tool (compile, tsc, pytest), never by a model: a call with such a task type is a bug.

Everything is overridable by environment so model ids, limits and timeouts stay configuration:
  LLM_MAX_TOKENS_HEAVY / LLM_MAX_TOKENS_LIGHT, LLM_TIMEOUT_HEAVY / LLM_TIMEOUT_LIGHT (seconds),
  LLM_MAX_TOKENS_CEILING (the most a truncation retry may grow to).
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import os
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from aether_os.core.llm.budget import get_budget_manager
from aether_os.core.llm.plans import PLATFORM_ORG
from aether_os.core.errors import LLMTruncated, LLMUnavailable
from aether_os.core.model_router_providers import ModelSpec

logger = logging.getLogger(__name__)

HEAVY, LIGHT, NONE = "heavy", "light", "none"

_DEFAULTS = {HEAVY: (16384, 240), LIGHT: (6144, 90)}   # (max_tokens, timeout seconds)

_LIMIT_OVERRIDE = {"documentation": 12288}   # light model, but a README / handbook is long output

_TIER_OF = {
    # heavy
    "code_generation": HEAVY, "architecture": HEAVY, "analysis": HEAVY, "design": HEAVY, "ui_component": HEAVY,
    "security_scan": HEAVY, "testing": HEAVY, "review": HEAVY, "business_logic": HEAVY,
    # light
    "code_fix": LIGHT, "ci_repair": LIGHT, "code_refinement": LIGHT, "code_review": LIGHT, "ui_critique": LIGHT,
    "documentation": LIGHT, "summarize": LIGHT, "classify": LIGHT, "requirements": LIGHT, "intake": LIGHT,
    "portal": LIGHT, "verify": LIGHT,
    # none: a tool answers these
    "syntax_check": NONE, "type_check": NONE, "import_check": NONE, "test_result": NONE,
}


@dataclass(frozen=True)
class TaskProfile:
    tier: str
    max_tokens: int
    timeout_s: int


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    value = int(raw) if raw.lstrip("+").isdigit() else 0
    if value > 0:
        return value
    logger.warning("%s=%r is not a positive integer, using %d", name, raw, default)
    return default


def profile_for(task_type: str) -> TaskProfile:
    """Unknown task types are heavy: a too-small limit truncates, a too-large one only costs headroom."""
    tier = _TIER_OF.get(task_type, HEAVY)
    if tier == NONE:
        return TaskProfile(NONE, 0, 0)
    tokens, timeout = _DEFAULTS[tier]
    suffix = tier.upper()
    tokens = _LIMIT_OVERRIDE.get(task_type, tokens)
    return TaskProfile(tier, _env_int(f"LLM_MAX_TOKENS_{suffix}", tokens), _env_int(f"LLM_TIMEOUT_{suffix}", timeout))


def resolve_max_tokens(task_type: str, requested: Optional[int]) -> int:
    """The caller's explicit limit wins; None means 'the task type's limit'."""
    if requested:
        return requested
    profile = profile_for(task_type)
    if profile.tier == NONE:
        raise ValueError(f"task type {task_type!r} is answered by a tool (compile, tsc, pytest), not by a model")
    return profile.max_tokens


def tiered_chain(chain: list, task_type: str) -> list:
    """Put the tier's model first among the openrouter entries: OPENROUTER_HEAVY_MODEL for heavy tasks,
    OPENROUTER_LIGHT_MODEL for light ones. Other providers keep their place; with no env model the chain is unchanged."""
    tier = profile_for(task_type).tier
    wanted = os.environ.get(f"OPENROUTER_{tier.upper()}_MODEL", "").strip() if tier in (HEAVY, LIGHT) else ""
    ours = [s for s in chain if s.provider == "openrouter"]
    if not wanted or not ours or ours[0].model == wanted:
        return chain
    first = next((s for s in ours if s.model == wanted), None) or ModelSpec("openrouter", wanted, ours[0].timeout_seconds, 1)
    ordered = [first] + [s for s in ours if s is not first]
    out, placed = [], False
    for spec in chain:
        if spec.provider != "openrouter":
            out.append(spec)
        elif not placed:
            out.extend(ordered)
            placed = True
    return out


# Set for the single growth retry: the provider client then also switches reasoning off (KAN-259).
retry_without_reasoning: contextvars.ContextVar[bool] = contextvars.ContextVar("retry_without_reasoning", default=False)


def reasoning_floor() -> int:
    """Smallest max_tokens sent to a reasoning-capable provider; LLM_MAX_TOKENS_FLOOR overrides."""
    return _env_int("LLM_MAX_TOKENS_FLOOR", 4096)


def is_truncated(choice: dict, usage: Optional[dict]) -> bool:
    """True when the reply was cut off: finish_reason=length, or NO visible content while the model spent tokens
    reasoning (reasoning_tokens>0 or a reasoning field). The second case is what a 2000-token limit produced
    on Nemotron: finish_reason 'stop' or None, content empty, every token spent thinking."""
    if choice.get("finish_reason") == "length":
        return True
    message = choice.get("message") or {}
    if (message.get("content") or "").strip():
        return False
    details = (usage or {}).get("completion_tokens_details") or {}
    return bool(details.get("reasoning_tokens") or message.get("reasoning") or message.get("reasoning_content"))


def grown_max_tokens(current: int) -> int:
    """Limit for the single retry after a truncated reply: double, capped at LLM_MAX_TOKENS_CEILING."""
    return min(current * 2, max(_env_int("LLM_MAX_TOKENS_CEILING", 32768), current))


async def record_truncated(org_id: Optional[str], model: str, prompt: str, output_tokens: int, enforce_local: bool) -> None:
    """A truncated reply was generated and billed but returns no text, so the success path never books it."""
    if enforce_local and not org_id:
        return
    try:
        await get_budget_manager().record_usage(org_id=org_id or PLATFORM_ORG, input_tokens=len(prompt) // 4,
                                                output_tokens=output_tokens, model=model, cache_hit=False)
    except Exception as exc:
        logger.warning("Budget record for a truncated reply failed (spend not recorded): %s", exc)


async def call_with_growth(call: Callable[[int], Awaitable[str]], max_tokens: int, timeout: float, label: str,
                           admit: Optional[Callable[[int], Awaitable[object]]] = None,
                           record: Optional[Callable[[int], Awaitable[None]]] = None) -> str:
    """Run call(max_tokens); if the reply was truncated, retry ONCE on the same model with a larger limit.
    A second cut-off raises LLMTruncated with the reason: a truncated reply is never returned, so nobody writes it.

    A truncated reply was still generated and billed, so record(n) books it (n output tokens: the limit it hit) on
    both attempts. The larger request is a new spend: admit(n) (the budget check for that worst case) must pass
    before the retry, and a refusal ends the call with the truncation error instead of skipping the cap."""
    try:
        return await asyncio.wait_for(call(max_tokens), timeout=timeout)
    except LLMTruncated as first:
        if record:
            await record(max_tokens)
        bigger = grown_max_tokens(max_tokens)
        if bigger <= max_tokens:
            raise
        if admit:
            try:
                await admit(bigger)
            except LLMUnavailable as refused:
                raise LLMTruncated(f"{label}: reply truncated at max_tokens={max_tokens} and the retry at {bigger} "
                                   f"was refused by the budget check ({refused})") from first
        logger.warning("%s truncated at max_tokens=%d, retrying once at %d", label, max_tokens, bigger)
        token = retry_without_reasoning.set(True)
        try:
            return await asyncio.wait_for(call(bigger), timeout=timeout)
        except LLMTruncated as second:
            if record:
                await record(bigger)
            raise LLMTruncated(f"{label}: reply truncated at max_tokens={max_tokens} and again at {bigger}; "
                               f"raise LLM_MAX_TOKENS_* / LLM_MAX_TOKENS_CEILING or shrink the request ({second})") from first
        finally:
            retry_without_reasoning.reset(token)
