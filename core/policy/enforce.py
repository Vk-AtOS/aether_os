"""AetherOS — policy enforcement: gather the facts, evaluate the rules, ledger every denial.

Fail closed: if the facts cannot be read, the answer is a denial (policy_unavailable).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from sqlalchemy import func, select

from aether_os.core.audit.ledger import get_ledger
from aether_os.core.billing.payments import effective_plan
from aether_os.core.db import get_session_factory
from aether_os.core.models import Organisation, Run
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
        in_period = (await session.execute(
            select(func.count()).select_from(Run)
            .where(Run.org_id == org_id, Run.started_at >= now - QUOTA_PERIOD_SECONDS))).scalar() or 0
    return Facts(
        org_exists=True, org_deleted=bool(org.is_deleted),
        plan=effective_plan(org.plan, org.plan_period_end, now), role=role,
        active_runs=active, runs_in_period=in_period,
        trial_runs_used=org.trial_runs_used or 0, trial_runs_limit=org.trial_runs_limit or 0,
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
        logger.info("policy: denied %s org=%s role=%s reason=%s", action, org_id, role, decision.reason)
        await get_ledger().async_log_audit_event(
            org_id=org_id or "-", user_id=actor, action="policy.denied",
            resource_type="policy_action", resource_id=resource_id or action,
            metadata={"action": action, "reason": decision.reason, "role": role, **decision.detail},
        )
    return decision
