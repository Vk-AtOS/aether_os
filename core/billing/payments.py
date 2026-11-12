"""AetherOS — accepted provider payments (replay protection) and paid periods.

Every provider order / payment that changes an org's plan is recorded here, in
the same transaction as the plan change. The unique constraints make the
database the arbiter: a second presentation of the same order or payment, even
one racing the first, cannot be applied again.

A payment buys PERIOD_SECONDS of the plan. The period end is stored on the org
(`plan_period_end`); once it has passed the org is on the free plan. That is
decided when the plan is read (effective_plan / expire_if_due), never by a
background job, so a missed job cannot leave an unpaid org on a paid plan.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import Float, Integer, String, UniqueConstraint, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from aether_os.core.audit.ledger import get_ledger
from aether_os.core.db import Base, get_session_factory
from aether_os.core.models import Organisation

logger = logging.getLogger(__name__)

PERIOD_SECONDS = 30 * 86400
FREE_PLAN = "free"
_UNPAID_PLANS = ("free", "trial")


class BillingPayment(Base):
    __tablename__ = "billing_payments"
    __table_args__ = (
        UniqueConstraint("provider", "order_id", name="uq_billing_payments_order"),
        UniqueConstraint("provider", "payment_id", name="uq_billing_payments_payment"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    payment_id: Mapped[str] = mapped_column(String(100), nullable=False)
    org_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    plan: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # minor units, as the provider reports it
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)


def effective_plan(plan: Optional[str], period_end: Optional[float], now: Optional[float] = None) -> str:
    """The plan in force: a paid plan whose period has ended counts as free."""
    plan = plan or "trial"
    if plan not in _UNPAID_PLANS and period_end is not None and period_end <= (time.time() if now is None else now):
        return FREE_PLAN
    return plan


def next_period_end(current_plan: Optional[str], current_end: Optional[float], paid_plan: str, now: float) -> float:
    """Paying for the plan already in force extends it from its current end;
    anything else (lapsed, first payment, a different plan) starts at payment time."""
    renewing = current_plan == paid_plan and current_end is not None and current_end > now
    return (current_end if renewing else now) + PERIOD_SECONDS


async def _ledger(org_id: str, action: str, metadata: Dict[str, Any]) -> None:
    await get_ledger().async_log_audit_event(
        org_id=org_id, user_id="billing", action=action,
        resource_type="organisation", resource_id=org_id, metadata=metadata)


async def expire_if_due(session, org: Organisation, now: Optional[float] = None) -> str:
    """Return the org's plan in force; if its paid period has ended, record that once.

    Called wherever a request's identity is established, so the stored plan is
    corrected by the org's own next request. The guarded UPDATE means concurrent
    requests write (and ledger) the expiry exactly once. plan_period_end is kept,
    so the status endpoint can say when the plan lapsed.
    """
    now = time.time() if now is None else now
    stored, period_end = org.plan, org.plan_period_end
    plan = effective_plan(stored, period_end, now)
    if plan == stored or plan != FREE_PLAN:
        return plan
    result = await session.execute(
        update(Organisation)
        .where(Organisation.id == org.id, Organisation.plan == stored, Organisation.plan_period_end <= now)
        .values(plan=FREE_PLAN))
    await session.commit()
    if result.rowcount:
        logger.info("billing: org=%s plan %s expired at %s — now free", org.id, stored, period_end)
        await _ledger(org.id, "billing.period_expired", {"previous_plan": stored, "period_end": period_end})
        return FREE_PLAN
    # Someone else changed the row first (a payment, or another request's expiry): read what is true now.
    row = (await session.execute(
        select(Organisation.plan, Organisation.plan_period_end).where(Organisation.id == org.id))).first()
    return effective_plan(row[0], row[1], now) if row else FREE_PLAN


async def apply_paid_order(provider: str, order_id: str, payment_id: str,
                           org_id: str, plan: str, amount: Optional[int] = None) -> bool:
    """Record the payment, set the org's plan and paid period, atomically, at most once.

    Returns False (and changes nothing) when
    this order or payment was already applied or the org does not exist. The
    caller must have verified the payment with the provider first.
    """
    now = time.time()
    async with get_session_factory()() as session:
        session.add(BillingPayment(provider=provider, order_id=order_id, payment_id=payment_id,
                                   org_id=org_id, plan=plan, amount=amount, created_at=now))
        try:
            await session.flush()  # the unique constraints decide before the plan is touched
            # Row lock: two different payments for one org must extend the period one after the other.
            org = (await session.execute(
                select(Organisation).where(Organisation.id == org_id).with_for_update())).scalar_one_or_none()
            if org is None:
                await session.rollback()
                logger.warning("billing: %s order=%s is for unknown org=%s — not applied", provider, order_id, org_id)
                return False
            previous_plan, previous_end = org.plan, org.plan_period_end
            period_end = next_period_end(previous_plan, previous_end, plan, now)
            org.plan, org.plan_period_end = plan, period_end
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            logger.warning("billing: %s order=%s payment=%s presented again for org=%s — refused (%s)",
                           provider, order_id, payment_id, org_id, type(exc).__name__)
            return False
    renewed = period_end - now > PERIOD_SECONDS
    await _ledger(org_id, "billing.period_renewed" if renewed else "billing.period_started", {
        "provider": provider, "order_id": order_id, "payment_id": payment_id, "plan": plan,
        "amount": amount, "paid_at": now, "period_end": period_end,
        "previous_plan": previous_plan, "previous_period_end": previous_end,
    })
    return True


async def billing_status(org_id: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Plan in force and its paid period for one org; None if the org does not exist."""
    now = time.time() if now is None else now
    async with get_session_factory()() as session:
        org = (await session.execute(select(Organisation).where(Organisation.id == org_id))).scalar_one_or_none()
        if org is None:
            return None
        period_end = org.plan_period_end
        plan = await expire_if_due(session, org, now)
    active = period_end is not None and period_end > now
    return {
        "plan": plan,
        "period_end": period_end,  # unix seconds; null when the org has never had a paid period
        "period_active": active,
        "days_remaining": int((period_end - now) // 86400) if active else (0 if period_end is not None else None),
        "period_days": PERIOD_SECONDS // 86400,
    }
