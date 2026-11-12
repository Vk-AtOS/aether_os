"""Prime — delegation repository. Used by humans/admin code; Prime itself never writes here."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from sqlalchemy import select

from aether_os.core.audit import chain as audit_chain
from aether_os.core.db import get_session_factory
from aether_os.prime.authz import Delegation, Limits
from aether_os.prime.limits import get_limits
from aether_os.prime.models import PrimeDelegation


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt else None


def _aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.replace(tzinfo=timezone.utc) if dt else None


def org_payload(org_id: Optional[str]) -> dict:
    """Ledger payload fragment: entries carry org_id so the ledger can be read per organisation."""
    return {"org_id": org_id} if org_id else {}


def _to_domain(row: PrimeDelegation) -> Delegation:
    return Delegation(
        id=row.id, grantor=row.grantor, deputy=row.deputy, scope=frozenset(row.scope),
        limits=(Limits(max_amount=row.max_amount, currency=row.currency)
                if row.max_amount is not None and row.currency else None),
        autonomy=row.autonomy,
        valid_from=_aware_utc(row.valid_from), valid_until=_aware_utc(row.valid_until),
        revoked_at=_aware_utc(row.revoked_at), revoked_by=row.revoked_by,
    )


class DelegationRepository:
    async def add(self, d: Delegation, org_id: Optional[str] = None) -> None:
        """Store a delegation. Raises ValueError if it breaks the organisation's limits."""
        limits = await get_limits(org_id)
        if d.valid_until - d.valid_from > timedelta(days=limits.max_delegation_days):
            raise ValueError(f"delegation may last at most {limits.max_delegation_days} days")
        if d.limits and d.limits.max_amount > limits.payment_ceiling:
            raise ValueError(f"amount limit cannot be above the payment ceiling "
                             f"{limits.payment_ceiling}")
        # Ledger first: a delegation must never exist without a record of who granted it.
        await audit_chain.append(
            actor=d.grantor, action="prime.delegation.grant",
            payload={**d.model_dump(mode="json"), **org_payload(org_id)},
        )
        async with get_session_factory()() as session:
            session.add(PrimeDelegation(
                id=d.id, grantor=d.grantor, deputy=d.deputy, scope=sorted(d.scope),
                max_amount=str(d.limits.max_amount) if d.limits else None,
                currency=d.limits.currency if d.limits else None,
                autonomy=int(d.autonomy),
                valid_from=_naive_utc(d.valid_from), valid_until=_naive_utc(d.valid_until),
                revoked_at=_naive_utc(d.revoked_at), revoked_by=d.revoked_by,
            ))
            await session.commit()

    async def for_grantor(self, grantor: str) -> List[Delegation]:
        async with get_session_factory()() as session:
            rows = (await session.execute(
                select(PrimeDelegation).where(PrimeDelegation.grantor == grantor)
            )).scalars().all()
        return [_to_domain(r) for r in rows]

    async def for_deputy(self, identities: Iterable[str]) -> List[Delegation]:
        """Delegations naming any of these identities (user id, email) as deputy."""
        async with get_session_factory()() as session:
            rows = (await session.execute(
                select(PrimeDelegation).where(PrimeDelegation.deputy.in_(list(identities)))
            )).scalars().all()
        return [_to_domain(r) for r in rows]

    async def get(self, delegation_id: str) -> Optional[Delegation]:
        async with get_session_factory()() as session:
            row = await session.get(PrimeDelegation, delegation_id)
        return _to_domain(row) if row else None

    async def revoke(self, delegation_id: str, by: str, now: datetime,
                     org_id: Optional[str] = None) -> bool:
        """Mark a delegation revoked. Returns False if it does not exist."""
        async with get_session_factory()() as session:
            row = await session.get(PrimeDelegation, delegation_id)
            if row is None:
                return False
            if row.revoked_at is None:  # keep the first revocation on record
                await audit_chain.append(
                    actor=by, action="prime.delegation.revoke",
                    payload={"delegation_id": delegation_id, **org_payload(org_id)},
                )
                row.revoked_at = _naive_utc(now)
                row.revoked_by = by
                await session.commit()
            return True
