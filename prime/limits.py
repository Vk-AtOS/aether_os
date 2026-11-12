"""Prime — per-organisation limits (payment ceiling, longest delegation).

Defaults come from prime/authz.py. An organisation admin may change them inside
the HARD_* bounds; every change is written to the ledger before it is stored.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from aether_os.core.audit import chain as audit_chain
from aether_os.core.db import get_session_factory
from aether_os.prime.authz import (
    HARD_MAX_DELEGATION_DURATION, HARD_PAYMENT_CEILING, MAX_DELEGATION_DURATION,
    PAYMENT_CEILING,
)
from aether_os.prime.models import PrimeOrgLimits


@dataclass(frozen=True)
class OrgLimits:
    payment_ceiling: Decimal
    max_delegation_days: int


DEFAULT_LIMITS = OrgLimits(PAYMENT_CEILING, MAX_DELEGATION_DURATION.days)


def validate(payment_ceiling: Decimal, max_delegation_days: int) -> OrgLimits:
    if not payment_ceiling.is_finite() or payment_ceiling <= 0:
        raise ValueError("payment ceiling must be a positive amount")
    if payment_ceiling > HARD_PAYMENT_CEILING:
        raise ValueError(f"payment ceiling cannot be above {HARD_PAYMENT_CEILING}")
    if not 1 <= max_delegation_days <= HARD_MAX_DELEGATION_DURATION.days:
        raise ValueError("longest delegation must be between 1 and "
                         f"{HARD_MAX_DELEGATION_DURATION.days} days")
    return OrgLimits(payment_ceiling, max_delegation_days)


async def get_limits(org_id: Optional[str]) -> OrgLimits:
    """Limits for an organisation. A stored row outside the hard bounds raises
    (callers fail closed) rather than being silently trusted."""
    if not org_id:
        return DEFAULT_LIMITS
    async with get_session_factory()() as session:
        row = await session.get(PrimeOrgLimits, org_id)
    if row is None:
        return DEFAULT_LIMITS
    return validate(Decimal(row.payment_ceiling), row.max_delegation_days)


async def set_limits(org_id: str, by: str, payment_ceiling: Decimal,
                     max_delegation_days: int) -> OrgLimits:
    new = validate(payment_ceiling, max_delegation_days)
    old = await get_limits(org_id)
    if new == old:
        return new
    # Ledger first: a limit must never change without a record of who changed it.
    await audit_chain.append(actor=by, action="prime.limits.change", payload={
        "org_id": org_id,
        "from": {"payment_ceiling": str(old.payment_ceiling),
                 "max_delegation_days": old.max_delegation_days},
        "to": {"payment_ceiling": str(new.payment_ceiling),
               "max_delegation_days": new.max_delegation_days},
    })
    async with get_session_factory()() as session:
        row = await session.get(PrimeOrgLimits, org_id)
        if row is None:
            row = PrimeOrgLimits(org_id=org_id)
            session.add(row)
        row.payment_ceiling = str(new.payment_ceiling)
        row.max_delegation_days = new.max_delegation_days
        row.updated_by = by
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.commit()
    return new
