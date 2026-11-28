"""AetherOS - the single answer to "is this run autonomous?" for every human approval gate (KAN-248).

Before this module each gate (p00 Gate 1, spec review, p05 Gate 3 and Gate 2) had its own copy of the
check and none read the request's `mode`, so a default API build (mode="autonomous") still blocked on
four human gates. Precedence, most specific first:

  0. CEILING: an organisation that requires human review (Organisation.require_human_review) is never
     autonomous, whatever the request says. A request may always make a run stricter.
  1. the request mode stored in the run context ("mode"): "autonomous" -> yes;
     "supervised" / "manual" / "guided" -> no (a person asked to be in the loop)
  2. the organisation's autonomous_mode
  3. env AUTONOMOUS_MODE=true (deployment-wide switch)
The organisation values are read from the database at the gate, never from the mutable run context.

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
    source: str  # request | organisation | env | default | organisation_requires_review | org_unreadable


class OrgPolicy(NamedTuple):
    org_id: Optional[str]
    autonomous: bool        # Organisation.autonomous_mode
    requires_review: bool   # Organisation.require_human_review: the explicit ceiling


def resolve_autonomy(ctx: Optional[Dict[str, Any]], org_autonomous: bool = False,
                     org_requires_review: bool = False) -> Autonomy:
    """Is this run autonomous, and which source decided it.

    The organisation's "require human review" setting is a CEILING: no request can lift it. A request
    may always make a run stricter. Without that setting, the request mode decides, then the org's
    autonomous_mode, then env. `org_*` must come from the database (see resolve_run_autonomy), never
    from the mutable run context.
    """
    if org_requires_review:
        return Autonomy(False, "organisation_requires_review")
    mode = str((ctx or {}).get("mode") or "").strip().lower()
    if mode in AUTONOMOUS_MODES:
        return Autonomy(True, "request")
    if mode in SUPERVISED_MODES:
        return Autonomy(False, "request")
    if org_autonomous:
        return Autonomy(True, "organisation")
    if os.environ.get("AUTONOMOUS_MODE", "").lower() == "true":
        return Autonomy(True, "env")
    return Autonomy(False, "default")


async def load_org_policy(run_id: str) -> Optional[OrgPolicy]:
    """The organisation's gate policy for this run, read from the database now (None if unreadable)."""
    try:
        from sqlalchemy import select
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Organisation, Run
        async with get_session_factory()() as session:
            row = (await session.execute(
                select(Run.org_id, Organisation.autonomous_mode, Organisation.require_human_review)
                .join(Organisation, Organisation.id == Run.org_id, isouter=True)
                .where(Run.id == run_id))).first()
    except Exception as e:
        logger.warning("autonomy: could not read the organisation policy of run %s: %s", run_id, e)
        return None
    if row is None:
        return None
    return OrgPolicy(row[0], bool(row[1]), bool(row[2]))


async def resolve_run_autonomy(run_id: Optional[str], ctx: Optional[Dict[str, Any]]) -> Autonomy:
    """resolve_autonomy for a live run: the org policy comes from the database, so mutating the run
    context cannot raise autonomy. If it cannot be read the run is supervised (fail closed).
    With no run id nothing can wait or be recorded, so only the context and env are consulted.
    """
    ctx = ctx if ctx is not None else {}
    if not run_id:
        return resolve_autonomy(ctx, org_autonomous=(
            ctx.get("autonomous_mode") is True or ctx.get("decision_mode") == "autonomous"))
    return autonomy_for_policy(run_id, ctx, await load_org_policy(run_id))


def autonomy_for_policy(run_id: str, ctx: Dict[str, Any], policy: Optional[OrgPolicy]) -> Autonomy:
    """resolve_autonomy with a policy already loaded; an unreadable policy (None) means supervised."""
    if policy is None:
        return Autonomy(False, "org_unreadable")
    result = resolve_autonomy(ctx, policy.autonomous, policy.requires_review)
    if policy.requires_review and str(ctx.get("mode") or "").lower() in AUTONOMOUS_MODES:
        logger.warning("autonomy: run %s asked for mode=autonomous but its organisation requires human "
                       "review; the gates will wait for a person", run_id)
    return result


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
    """Fail closed: anything but an explicit approval stops the run."""
    status = getattr(resolved, "status", None)
    if status == "approved":
        return
    if status == "timeout":
        raise PipelineBlockedError(gate_wait_reason(gate, getattr(resolved, "timeout_seconds", 0)))
    if status == "denied":
        raise PipelineBlockedError(f"{gate} was denied by a human; the run was stopped.")
    # expired, pending, unknown: only an explicit approval lets the run continue.
    raise PipelineBlockedError(f"{gate} was not approved (status: {status}); the run was stopped.")
