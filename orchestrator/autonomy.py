"""AetherOS - the single answer to "is this run autonomous?" for every human approval gate (KAN-248).

Before this module each gate (p00 Gate 1, spec review, p05 Gate 3 and Gate 2) had its own copy of the
check and none read the request's `mode`, so a default API build (mode="autonomous") still blocked on
four human gates. Precedence, most specific first:

  1. the request mode stored in the run context ("mode"): "autonomous" -> yes;
     "supervised" / "manual" / "guided" -> no (a person asked to be in the loop)
  2. the organisation setting (autonomous_mode / decision_mode in the context, or the value the
     caller read from the database)
  3. env AUTONOMOUS_MODE=true (deployment-wide switch)

In autonomous mode a gate does not wait: it records an auditable approved decision row
(human_choice="autonomous", the reason in `why`) and carries on.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, NamedTuple, Optional

from aether_os.core.errors import PipelineBlockedError

logger = logging.getLogger(__name__)

AUTONOMOUS_MODES = {"autonomous", "auto"}
SUPERVISED_MODES = {"supervised", "manual", "guided", "approval_required"}
AUTONOMOUS_WHO = "autonomous"


class Autonomy(NamedTuple):
    autonomous: bool
    source: str  # request | organisation | env | default


def resolve_autonomy(ctx: Optional[Dict[str, Any]], org_autonomous: Optional[bool] = None) -> Autonomy:
    """Is this run autonomous, and which source decided it.

    `org_autonomous`: the organisation setting as read from the database by the caller. When given it
    replaces the copies in `ctx` (the context is mutable, the database is the setting in force).
    """
    ctx = ctx or {}
    mode = str(ctx.get("mode") or "").strip().lower()
    if mode in AUTONOMOUS_MODES:
        return Autonomy(True, "request")
    if mode in SUPERVISED_MODES:
        return Autonomy(False, "request")
    if org_autonomous is None:
        org_autonomous = ctx.get("autonomous_mode") is True or ctx.get("decision_mode") == "autonomous"
    if org_autonomous:
        return Autonomy(True, "organisation")
    if os.environ.get("AUTONOMOUS_MODE", "").lower() == "true":
        return Autonomy(True, "env")
    return Autonomy(False, "default")


async def record_autonomous_decision(
    *, run_id: str, org_id: Optional[str], decision_type: str, title: str, phase: str,
    what: str, source: str,
) -> None:
    """Write the approved decision row an autonomous gate leaves instead of waiting.

    A failure to write is logged, never raised: the audit row must not stop a build the owner asked
    to run unattended.
    """
    try:
        from aether_os.core.decisions.decision_engine import Decision, get_decision_engine
        now = time.time()
        await get_decision_engine().request_approval(Decision(
            run_id=run_id, org_id=org_id or "-", decision_type=decision_type, title=title, what=what,
            why=f"Auto-approved: run is autonomous (decided by {source}); no human approval was requested.",
            phase=phase, status="approved", human_choice=AUTONOMOUS_WHO, decided_at=now))
    except Exception as e:
        logger.warning("autonomy: could not record the auto-approval of %s for run %s: %s", title, run_id, e)


def gate_wait_reason(gate: str, seconds: float) -> str:
    """Why a supervised run stopped at a gate nobody answered (never a model-provider message)."""
    return (f"Waited {int(seconds)} s for a human approval of {gate}; nobody answered, "
            "so the run was stopped. Restart it and approve the gate, or start it with mode=autonomous.")


def halt_unless_approved(resolved: Any, gate: str) -> None:
    """A denied or unanswered (timeout) gate must stop the run."""
    if resolved.status == "timeout":
        raise PipelineBlockedError(gate_wait_reason(gate, getattr(resolved, "timeout_seconds", 0)))
    if resolved.status == "denied":
        raise PipelineBlockedError(f"{gate} was denied by a human; the run was stopped.")
