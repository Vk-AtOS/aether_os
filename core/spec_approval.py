"""AetherOS — the one way a build's specification review gate is decided.

Every approver goes through decide_spec(): a signed-in user (POST
/factory/runs/{id}/approve-spec), the client portal (POST /portal/{id}/approve)
and Prime's aetheros.run_gate executor. It checks the run belongs to the org,
releases the gate only while the run is actually waiting there, and writes who
decided to the ledger.

ponytail: get_control then set_control is not atomic, so two approvers racing
each other can both be ledgered as releasing the gate (the gate is released
once either way). Use a Redis compare-and-set if a single winner matters.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import select

from aether_os.core.audit.ledger import get_ledger
from aether_os.core.db import get_session_factory
from aether_os.core.models import Run
from aether_os.core.pipeline_state import get_control, set_control

logger = logging.getLogger(__name__)

WAITING = "spec_review"   # what orchestrator/spec_review_gate.py sets while it waits


async def decide_spec(run_id: str, org_id: str, actor: str, via: str, approve: bool = True,
                      metadata: Optional[Dict[str, Any]] = None) -> str:
    """Approve (or cancel) the run's specification. Returns one of:

    "approved" / "cancelled" — the gate was released and the decision ledgered;
    "not_found"              — no such run in this org (nothing changed);
    "not_waiting:<state>"    — the run is not at the review gate (nothing changed).

    `actor` is who decided (user id, "portal_token:<id>", "prime:<request id>"),
    `via` is the channel ("dashboard", "client_portal", "prime").
    """
    async with get_session_factory()() as session:
        found = (await session.execute(
            select(Run.id).where(Run.id == run_id, Run.org_id == org_id))).scalar_one_or_none()
    if not found:
        return "not_found"
    state = await get_control(run_id)
    if state != WAITING:
        return f"not_waiting:{state}"
    await set_control(run_id, "spec_approved" if approve else "cancel")
    outcome = "approved" if approve else "cancelled"
    await get_ledger().async_log_audit_event(
        org_id=org_id, user_id=actor, action=f"run.spec_{outcome}",
        resource_type="run", resource_id=run_id, metadata={"via": via, **(metadata or {})},
    )
    logger.info("spec review of run %s %s by %s via %s", run_id, outcome, actor, via)
    return outcome
