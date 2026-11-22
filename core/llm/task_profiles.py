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
import logging
import os
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from aether_os.core.errors import LLMTruncated
from aether_os.core.model_router_providers import ModelSpec

logger = logging.getLogger(__name__)

HEAVY, LIGHT, NONE = "heavy", "light", "none"

_DEFAULTS = {HEAVY: (16384, 240), LIGHT: (4096, 90)}   # (max_tokens, timeout seconds)

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
    try:
        value = int(raw)
        if value > 0:
            return value
    except ValueError:
        pass
    logger.warning("%s=%r is not a positive integer, using %d", name, raw, default)
    return default


def profile_for(task_type: str) -> TaskProfile:
    """Unknown task types are heavy: a too-small limit truncates, a too-large one only costs headroom."""
    tier = _TIER_OF.get(task_type, HEAVY)
    if tier == NONE:
        return TaskProfile(NONE, 0, 0)
    tokens, timeout = _DEFAULTS[tier]
    suffix = tier.upper()
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


def grown_max_tokens(current: int) -> int:
    """Limit for the single retry after a truncated reply: double, capped at LLM_MAX_TOKENS_CEILING."""
    return min(current * 2, max(_env_int("LLM_MAX_TOKENS_CEILING", 32768), current))


async def call_with_growth(call: Callable[[int], Awaitable[str]], max_tokens: int, timeout: float, label: str) -> str:
    """Run call(max_tokens); if the reply was truncated, retry ONCE on the same model with a larger limit.
    A second cut-off raises LLMTruncated with the reason: a truncated reply is never returned, so nobody writes it."""
    try:
        return await asyncio.wait_for(call(max_tokens), timeout=timeout)
    except LLMTruncated as first:
        bigger = grown_max_tokens(max_tokens)
        if bigger <= max_tokens:
            raise
        logger.warning("%s truncated at max_tokens=%d, retrying once at %d", label, max_tokens, bigger)
        try:
            return await asyncio.wait_for(call(bigger), timeout=timeout)
        except LLMTruncated as second:
            raise LLMTruncated(f"{label}: reply truncated at max_tokens={max_tokens} and again at {bigger}; "
                               f"raise LLM_MAX_TOKENS_* / LLM_MAX_TOKENS_CEILING or shrink the request ({second})") from first
