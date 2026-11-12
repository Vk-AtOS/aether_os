"""
AetherOS — import audit_log rows that never reached a chain.

Rows written before the hash chain existed (or whose chain append failed and were
flagged chain_linked: false) are appended to their organisation's chain as
"imported" entries, oldest first, with their original timestamps. The payload says
`imported.content_chained_at_write: false`: the chain proves the row has not changed
since it was imported, not since it was first written. Emails and IPs are
pseudonymised on the way in, as for live events.

Idempotent: each imported row is recorded in `audit_backfill` in the same
transaction as its chain entry, so re-running imports nothing twice.

Run once after `alembic upgrade head`:  python3.11 -m aether_os.core.audit.backfill
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict

from sqlalchemy import Float, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from aether_os.core.audit import chain, subjects
from aether_os.core.db import Base, get_session_factory
from aether_os.core.models import AuditLog

logger = logging.getLogger(__name__)


class AuditBackfill(Base):
    __tablename__ = "audit_backfill"
    audit_log_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[float] = mapped_column(Float, nullable=False)


class _AlreadyImported(Exception):
    pass


def _metadata(text: Any) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except ValueError as e:
        logger.warning("audit_log metadata is not JSON, imported as text: %s", e)
        return {"raw": str(text)}
    return value if isinstance(value, dict) else {"raw": value}


async def _import(row: AuditLog) -> bool:
    ip_ref, meta = await subjects.scrub(row.org_id, row.ip_address, _metadata(row.log_metadata))

    async def _mark(session: AsyncSession, entry: chain.AuditChainEntry) -> None:
        # Checked inside the chain's lock: a concurrent run that imported this row
        # first has committed its marker, so this append is rolled back.
        if await session.get(AuditBackfill, row.id) is not None:
            raise _AlreadyImported(row.id)
        session.add(AuditBackfill(audit_log_id=row.id, entry_hash=entry.entry_hash,
                                  imported_at=time.time()))

    try:
        await chain.append(
            actor=row.user_id or "-", action=row.action, timestamp=row.created_at, also=_mark,
            payload={"org_id": row.org_id, "resource_type": row.resource_type,
                     "resource_id": row.resource_id, "metadata": meta, "ip_address": ip_ref,
                     "imported": {"from": "audit_log", "audit_log_id": row.id,
                                  "audit_log_prev_hash": row.prev_hash,
                                  "content_chained_at_write": False}})
    except _AlreadyImported:
        return False
    return True


async def backfill(batch: int = 500) -> int:
    """Import every audit_log row that has no chain entry yet. Returns how many."""
    imported = 0
    sf = get_session_factory()
    while True:
        async with sf() as session:
            rows = (await session.execute(
                select(AuditLog)
                .outerjoin(chain.AuditChainEntry, chain.AuditChainEntry.entry_hash == AuditLog.prev_hash)
                .outerjoin(AuditBackfill, AuditBackfill.audit_log_id == AuditLog.id)
                .where(chain.AuditChainEntry.seq.is_(None), AuditBackfill.audit_log_id.is_(None))
                .order_by(AuditLog.created_at, AuditLog.id).limit(batch))).scalars().all()
        if not rows:
            return imported
        for row in rows:
            imported += await _import(row)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"imported {asyncio.run(backfill())} audit_log rows into the audit chains")
