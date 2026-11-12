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

Run once after `alembic upgrade head`, dry run first (writes nothing):
    python3.11 -m aether_os.core.audit.backfill --dry-run
    python3.11 -m aether_os.core.audit.backfill [--batch 500] [--max-batches N]
Superadmins can do the same over HTTP: POST /prime/ledger/backfill (see
gateway/routers/ledger_ops_router.py).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import Float, String, and_, func, or_, select
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


_SAMPLE = 20  # problem ids listed in a report; the counts are always exact


def _pending(after: Optional[tuple], batch: int):
    """audit_log rows with no chain entry and no back-fill marker, oldest first, strictly
    after the keyset position `after` = (created_at, id). The keyset lets a run move past
    a row it could not import instead of selecting it forever."""
    q = (select(AuditLog)
         .outerjoin(chain.AuditChainEntry, chain.AuditChainEntry.entry_hash == AuditLog.prev_hash)
         .outerjoin(AuditBackfill, AuditBackfill.audit_log_id == AuditLog.id)
         .where(chain.AuditChainEntry.seq.is_(None), AuditBackfill.audit_log_id.is_(None)))
    if after:
        q = q.where(or_(AuditLog.created_at > after[0],
                        and_(AuditLog.created_at == after[0], AuditLog.id > after[1])))
    return q.order_by(AuditLog.created_at, AuditLog.id).limit(batch)


async def count_pending() -> int:
    async with get_session_factory()() as session:
        sub = (select(AuditLog.id)
               .outerjoin(chain.AuditChainEntry, chain.AuditChainEntry.entry_hash == AuditLog.prev_hash)
               .outerjoin(AuditBackfill, AuditBackfill.audit_log_id == AuditLog.id)
               .where(chain.AuditChainEntry.seq.is_(None), AuditBackfill.audit_log_id.is_(None)))
        return (await session.execute(select(func.count()).select_from(sub.subquery()))).scalar_one()


def _problem(row: AuditLog) -> Optional[str]:
    """Why this row would not import cleanly, or None. Pure: the dry run uses it."""
    try:
        chain.chain_id_for(row.org_id)
    except ValueError:
        return "org_id_cannot_name_a_chain"
    if row.log_metadata:
        try:
            if not isinstance(json.loads(row.log_metadata), dict):
                return "metadata_not_an_object"
        except ValueError:
            # Imported as {"raw": text}; free text is never pseudonymised, so look first.
            return "metadata_not_json"
    return None


async def run(batch: int = 500, *, dry_run: bool = False, max_batches: Optional[int] = None,
              on_progress: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Back-fill in batches and report. dry_run writes nothing (no chain entry, no
    pseudonym, no marker) and lists what a real run would do and which rows are problems.
    max_batches bounds one call; run again to continue (it is idempotent)."""
    report: Dict[str, Any] = {"dry_run": dry_run, "batches": 0, "pending_before": await count_pending(),
                              "by_chain": {}, "imported": 0, "failed": 0, "problems": {}}
    samples: Dict[str, List[str]] = {}
    after: Optional[tuple] = None
    while max_batches is None or report["batches"] < max_batches:
        async with get_session_factory()() as session:
            rows = (await session.execute(_pending(after, batch))).scalars().all()
        if not rows:
            break
        after = (rows[-1].created_at, rows[-1].id)
        report["batches"] += 1
        for row in rows:
            why = _problem(row)
            if why:
                report["problems"][why] = report["problems"].get(why, 0) + 1
                samples.setdefault(why, [])
                if len(samples[why]) < _SAMPLE:
                    samples[why].append(row.id)
            try:
                cid = chain.chain_id_for(row.org_id)
            except ValueError:
                report["failed"] += 0 if dry_run else 1
                continue
            report["by_chain"][cid] = report["by_chain"].get(cid, 0) + 1
            if dry_run:
                continue
            try:
                report["imported"] += await _import(row)
            except (ValueError, RuntimeError) as e:  # row stays pending; reported, not retried this run
                report["failed"] += 1
                logger.error("back-fill could not import audit_log %s: %s", row.id, type(e).__name__)
        if on_progress:
            on_progress({k: report[k] for k in ("batches", "imported", "failed")})
    report["problem_samples"] = samples
    report["remaining"] = await count_pending()
    report["clean"] = not report["problems"] and not report["failed"]
    return report


async def backfill(batch: int = 500) -> int:
    """Import every audit_log row that has no chain entry yet. Returns how many."""
    return (await run(batch))["imported"]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--max-batches", type=int, default=None)
    a = ap.parse_args()
    out = asyncio.run(run(a.batch, dry_run=a.dry_run, max_batches=a.max_batches,
                          on_progress=lambda p: logger.info("progress %s", p)))
    print(json.dumps(out, indent=2, sort_keys=True))
