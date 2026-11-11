"""AetherOS — accepted provider payments (replay protection).

Every provider order / payment that changes an org's plan is recorded here, in
the same transaction as the plan change. The unique constraints make the
database the arbiter: a second presentation of the same order or payment, even
one racing the first, cannot be applied again.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from sqlalchemy import Float, Integer, String, UniqueConstraint, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from aether_os.core.db import Base, get_session_factory
from aether_os.core.models import Organisation

logger = logging.getLogger(__name__)


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


async def apply_paid_order(provider: str, order_id: str, payment_id: str,
                           org_id: str, plan: str, amount: Optional[int] = None) -> bool:
    """Record the payment and set the org's plan, atomically, at most once.

    Returns False (and changes nothing) when this order or payment was already
    applied. The caller must have verified the payment with the provider first.
    """
    async with get_session_factory()() as session:
        session.add(BillingPayment(provider=provider, order_id=order_id, payment_id=payment_id,
                                   org_id=org_id, plan=plan, amount=amount))
        try:
            await session.flush()  # the unique constraints decide before the plan is touched
            await session.execute(
                update(Organisation).where(Organisation.id == org_id).values(plan=plan))
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            logger.warning("billing: %s order=%s payment=%s presented again for org=%s — refused (%s)",
                           provider, order_id, payment_id, org_id, type(exc).__name__)
            return False
    return True
