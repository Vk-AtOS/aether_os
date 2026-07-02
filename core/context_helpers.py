"""Context helpers — structured decision recording in accumulated_context.

The `decisions` list in accumulated_context lets downstream phases understand
*why* architectural choices were made rather than re-inferring them from raw
fields.  This prevents inconsistencies when e.g. phase 10 re-guesses the
database type that phase 2 already chose.

Public API
----------
    record_decision(ctx, key, value, reason, phase)
    get_decision(ctx, key) -> str | None
    get_decisions_summary(ctx) -> str
    validate_accumulated_context(ctx, phase_name) -> list[str]
    compress_context_for_prompt(ctx, relevant_keys) -> dict
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


def _ensure_decisions(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Guarantee ctx['decisions'] is a list and return it."""
    if not isinstance(ctx.get("decisions"), list):
        ctx["decisions"] = []
    return ctx["decisions"]


def record_decision(
    ctx: Dict[str, Any],
    key: str,
    value: str,
    reason: str,
    phase: str,
) -> None:
    """Append a structured decision to accumulated_context['decisions'].

    Parameters
    ----------
    ctx:
        The accumulated_context dict that flows through the pipeline.
    key:
        Short machine-readable identifier (e.g. "database", "auth_method",
        "multi_tenancy", "tenant_isolation").
    value:
        The chosen value (e.g. "PostgreSQL", "JWT", "True", "org_id_filter").
    reason:
        One sentence explaining *why* this value was chosen.  Downstream
        phases inject this into LLM prompts so the model does not re-invent
        the decision.
    phase:
        The phase name that made this decision (e.g. "p01", "p02").
    """
    decisions = _ensure_decisions(ctx)
    # Deduplicate: if the same key was already recorded in this phase, overwrite
    for entry in decisions:
        if entry.get("key") == key and entry.get("phase") == phase:
            entry["value"] = value
            entry["reason"] = reason
            entry["timestamp"] = datetime.datetime.utcnow().isoformat()
            logger.debug("[context_helpers] updated decision key=%s phase=%s value=%s", key, phase, value)
            return
    decisions.append({
        "key": key,
        "value": value,
        "reason": reason,
        "phase": phase,
        "timestamp": datetime.datetime.utcnow().isoformat(),
    })
    logger.debug("[context_helpers] recorded decision key=%s phase=%s value=%s", key, phase, value)


def get_decision(ctx: Dict[str, Any], key: str) -> Optional[str]:
    """Return the most recent recorded value for *key*, or None if not found."""
    decisions = _ensure_decisions(ctx)
    # Iterate in reverse so the most recent entry wins when duplicates exist
    for entry in reversed(decisions):
        if entry.get("key") == key:
            return str(entry["value"])
    return None


def get_decisions_summary(ctx: Dict[str, Any]) -> str:
    """Format all decisions as a readable block for LLM prompt injection.

    Example output::

        Architectural decisions already made (do not contradict these):
        - database (p02): PostgreSQL — multi_tenant=True requires row-level isolation
        - auth_method (p02): JWT — stateless; refresh token stored in httpOnly cookie
        - multi_tenancy (p01): True — B2B domain detected (SaaS keywords in spec)
    """
    decisions = _ensure_decisions(ctx)
    if not decisions:
        return ""
    lines = ["Architectural decisions already made (do not contradict these):"]
    for entry in decisions:
        key = entry.get("key", "?")
        phase = entry.get("phase", "?")
        value = entry.get("value", "?")
        reason = entry.get("reason", "")
        line = f"- {key} ({phase}): {value}"
        if reason:
            line += f" — {reason}"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Context schema validation
# ---------------------------------------------------------------------------

# Keys that every accumulated_context must have by the time a phase runs.
# Maps key -> expected Python type.
REQUIRED_CONTEXT_KEYS: Dict[str, Type] = {
    "project_name": str,
    "domain": str,
    "decisions": list,
    "phase_confidence": dict,
}


def validate_accumulated_context(ctx: Dict[str, Any], phase_name: str) -> List[str]:
    """Check that required keys are present and of the correct type.

    Returns a list of warning strings (empty = context is valid).
    Does NOT raise — callers log warnings and continue; a missing key is not
    fatal but may cause downstream prompts to be under-specified.

    Parameters
    ----------
    ctx:
        The accumulated_context dict that flows through the pipeline.
    phase_name:
        The phase calling this function, used in warning messages.
    """
    warnings: List[str] = []
    for key, expected_type in REQUIRED_CONTEXT_KEYS.items():
        if key not in ctx:
            warnings.append(
                f"[{phase_name}] accumulated_context missing required key '{key}' "
                f"(expected {expected_type.__name__})"
            )
        elif not isinstance(ctx[key], expected_type):
            actual = type(ctx[key]).__name__
            warnings.append(
                f"[{phase_name}] accumulated_context['{key}'] is {actual}, "
                f"expected {expected_type.__name__}"
            )
    for w in warnings:
        logger.warning("[context_helpers] %s", w)
    return warnings


# ---------------------------------------------------------------------------
# Context compression for prompt injection
# ---------------------------------------------------------------------------

def compress_context_for_prompt(
    ctx: Dict[str, Any],
    relevant_keys: List[str],
) -> Dict[str, Any]:
    """Return a filtered view of accumulated_context with only relevant keys.

    Avoids injecting the entire context dict into LLM prompts — large contexts
    waste tokens and dilute the signal.  Each phase should pass only the keys
    it actually needs.

    Parameters
    ----------
    ctx:
        The full accumulated_context dict.
    relevant_keys:
        List of top-level keys to include in the compressed view.
        Keys not present in ctx are silently omitted.

    Returns
    -------
    dict
        A new dict containing only the requested keys and their values.

    Example
    -------
    >>> compressed = compress_context_for_prompt(
    ...     ctx,
    ...     ["project_name", "domain", "decisions", "domain_ir_path"]
    ... )
    >>> prompt = f"Context: {json.dumps(compressed)}"
    """
    return {k: ctx[k] for k in relevant_keys if k in ctx}
