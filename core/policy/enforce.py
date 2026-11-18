"""AetherOS — policy enforcement: gather the facts, evaluate the rules, ledger every denial.

Fail closed: if the facts cannot be read, the answer is a denial (policy_unavailable).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from sqlalchemy import func, select, update

from aether_os.core.audit.ledger import get_ledger
from aether_os.core.billing.payments import effective_plan
from aether_os.core.db import get_session_factory
from aether_os.core.models import Organisation, Run, User
from aether_os.core.policy.rules import QUOTA_PERIOD_SECONDS, Decision, Facts, evaluate

logger = logging.getLogger(__name__)

_ACTIVE_RUN_STATUSES = ("running", "queued")


async def gather_facts(org_id: str, role: str, now: Optional[float] = None) -> Facts:
    now = time.time() if now is None else now
    async with get_session_factory()() as session:
        org = (await session.execute(
            select(Organisation).where(Organisation.id == org_id))).scalar_one_or_none() if org_id else None
        if org is None:
            return Facts(role=role)
        active = (await session.execute(
            select(func.count()).select_from(Run)
            .where(Run.org_id == org_id, Run.status.in_(_ACTIVE_RUN_STATUSES)))).scalar() or 0
        platform_active = (await session.execute(
            select(func.count()).select_from(Run)
            .where(Run.status.in_(_ACTIVE_RUN_STATUSES)))).scalar() or 0
        in_period = (await session.execute(
            select(func.count()).select_from(Run)
            .where(Run.org_id == org_id, Run.started_at >= now - QUOTA_PERIOD_SECONDS))).scalar() or 0
        seats = (await session.execute(
            select(func.count()).select_from(User)
            .where(User.org_id == org_id, User.is_active.is_(True), User.deleted_at.is_(None)))).scalar() or 0
    return Facts(
        seats_used=seats,
        org_exists=True, org_deleted=bool(org.is_deleted),
        plan=effective_plan(org.plan, org.plan_period_end, now), role=role,
        active_runs=active, runs_in_period=in_period,
        trial_runs_used=org.trial_runs_used or 0, trial_runs_limit=org.trial_runs_limit or 0,
        platform_active_runs=platform_active,
    )


async def _ledger_denial(action: str, decision: Decision, org_id: str, role: str,
                         actor: str, resource_id: str) -> None:
    logger.info("policy: denied %s org=%s role=%s reason=%s", action, org_id, role, decision.reason)
    await get_ledger().async_log_audit_event(
        org_id=org_id or "-", user_id=actor, action="policy.denied",
        resource_type="policy_action", resource_id=resource_id or action,
        metadata={"action": action, "reason": decision.reason, "role": role, **decision.detail},
    )


async def authorize(action: str, *, org_id: str, role: str, actor: str = "-",
                    resource_id: str = "") -> Decision:
    """Decide `action` for this caller. A denial is written to the ledger before it is returned."""
    try:
        decision = evaluate(action, await gather_facts(org_id, role))
    except Exception as exc:
        logger.warning("policy: could not read facts for %s (org=%s) — denying: %s", action, org_id, exc)
        decision = Decision(False, "policy_unavailable")
    if not decision.allowed:
        await _ledger_denial(action, decision, org_id, role, actor, resource_id)
    return decision


async def _consume_trial_run(org_id: str, now: float) -> bool:
    """Take one run from a trial org's allowance; False if none is left.

    One guarded UPDATE, so two starts racing for the last run cannot both get it.
    Orgs whose plan in force is not trial have no allowance to consume.
    """
    async with get_session_factory()() as session:
        org = (await session.execute(
            select(Organisation).where(Organisation.id == org_id))).scalar_one_or_none()
        if org is None:
            return False
        if effective_plan(org.plan, org.plan_period_end, now) != "trial":
            return True
        result = await session.execute(
            update(Organisation)
            .where(Organisation.id == org_id,
                   Organisation.trial_runs_used < Organisation.trial_runs_limit)
            .values(trial_runs_used=Organisation.trial_runs_used + 1))
        await session.commit()
        return bool(result.rowcount)


async def admit_new_run(*, org_id: str, role: str, actor: str = "-", resource_id: str = "") -> Decision:
    """The one gate for anything that starts a new build: policy check, then the
    atomic trial consume. Every path that creates a run calls this, never the two halves."""
    decision = await authorize("run.start", org_id=org_id, role=role, actor=actor, resource_id=resource_id)
    if not decision.allowed:
        return decision
    try:
        consumed = await _consume_trial_run(org_id, time.time())
    except Exception as exc:
        logger.warning("policy: trial allowance update failed (org=%s) — denying: %s", org_id, exc)
        consumed, decision = False, Decision(False, "policy_unavailable")
    if not consumed:
        if decision.allowed:  # lost the race for the last trial run
            decision = Decision(False, "trial_limit_reached")
        await _ledger_denial("run.start", decision, org_id, role, actor, resource_id)
    return decision
