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
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

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
