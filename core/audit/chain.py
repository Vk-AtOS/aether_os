"""
AetherOS — tamper-evident audit chain.

Append-only, hash-linked ledger. Every entry stores the hash of the previous
entry (`prev_hash`) and its own hash (`entry_hash`) over a canonical
serialisation of (prev_hash, timestamp, actor, action, payload). `verify()`
recomputes every hash and reports the first broken entry.

This module deliberately exposes no update, delete or purge operation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import weakref
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import Float, Integer, String, Text, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from aether_os.core.db import Base, get_session_factory

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64
# Appends are serialised (see append()). The retry below is only the backstop for
# writers the locks cannot see (a second process on SQLite): two writers that read
# the same tail collide on the primary key / unique prev_hash and the loser retries.
_APPEND_ATTEMPTS = 8
# Arbitrary constant naming "the audit chain tail" for pg_advisory_xact_lock.
_PG_CHAIN_LOCK_KEY = 0x41455448_434841  # "AETHCHA"
# One asyncio.Lock per event loop (a Lock cannot be shared across loops).
_loop_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = (
    weakref.WeakKeyDictionary())


def _local_lock() -> asyncio.Lock:
    """In-process lock: the whole serialisation on SQLite, and on PostgreSQL it keeps
    waiting appends from each holding a pooled connection."""
    loop = asyncio.get_running_loop()
    lock = _loop_locks.get(loop)
    if lock is None:
        lock = _loop_locks[loop] = asyncio.Lock()
    return lock
_VERIFY_PAGE = 1000


class AuditChainEntry(Base):
    __tablename__ = "audit_chain"

    # seq is assigned as tail+1 (not a DB sequence) so the chain has no gaps.
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # canonical JSON text
    # unique prev_hash: the DB itself rejects a fork (two entries after one parent).
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


def _reject_mutation(_mapper, _connection, target) -> None:
    raise RuntimeError(f"audit_chain is append-only (entry seq={target.seq})")


event.listen(AuditChainEntry, "before_update", _reject_mutation)
event.listen(AuditChainEntry, "before_delete", _reject_mutation)


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    entries_checked: int
    broken_seq: Optional[int] = None  # seq of the first broken entry
    reason: str = ""


def canonical_payload(payload: Dict[str, Any]) -> str:
    """Deterministic JSON text for a payload; this exact text is stored and hashed."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_entry_hash(prev_hash: str, timestamp: float, actor: str,
                       action: str, payload: str) -> str:
    """SHA-256 over the canonical serialisation of the five chained fields."""
    canonical = json.dumps([prev_hash, timestamp, actor, action, payload],
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def append(actor: str, action: str, payload: Optional[Dict[str, Any]] = None,
                 timestamp: Optional[float] = None) -> AuditChainEntry:
    """Append one entry. Raises if it cannot be written — callers must not assume success."""
    payload_text = canonical_payload(payload or {})
    ts = time.time() if timestamp is None else float(timestamp)
    sf = get_session_factory()
    last_error: Optional[Exception] = None
    async with _local_lock():
        for _ in range(_APPEND_ATTEMPTS):
            async with sf() as session:
                if session.get_bind().dialect.name == "postgresql":
                    # Cross-process serialisation: held until this transaction ends,
                    # so the tail read below cannot be shared with another writer.
                    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                                          {"k": _PG_CHAIN_LOCK_KEY})
                tail = (await session.execute(
                    select(AuditChainEntry).order_by(AuditChainEntry.seq.desc()).limit(1)
                )).scalars().first()
                prev_hash = tail.entry_hash if tail else GENESIS_HASH
                entry = AuditChainEntry(
                    seq=(tail.seq + 1) if tail else 1,
                    timestamp=ts, actor=actor, action=action, payload=payload_text,
                    prev_hash=prev_hash,
                    entry_hash=compute_entry_hash(prev_hash, ts, actor, action, payload_text),
                )
                session.add(entry)
                try:
                    await session.commit()
                    return entry
                except IntegrityError as e:
                    # Another writer took this position; re-read the tail and retry.
                    last_error = e
                    await session.rollback()
    raise RuntimeError(f"audit chain append lost {_APPEND_ATTEMPTS} races") from last_error


async def verify() -> ChainVerification:
    """Walk the chain from the first entry; report the first entry that does not check out.

    ponytail: truncating the tail is not detectable from the table alone —
    publish the latest entry_hash somewhere external if that threat matters.
    """
    sf = get_session_factory()
    checked = 0
    expected_prev = GENESIS_HASH
    last_seq = 0
    async with sf() as session:
        while True:
            rows = (await session.execute(
                select(AuditChainEntry).where(AuditChainEntry.seq > last_seq)
                .order_by(AuditChainEntry.seq).limit(_VERIFY_PAGE)
            )).scalars().all()
            if not rows:
                return ChainVerification(ok=True, entries_checked=checked)
            for row in rows:
                reason = ""
                if row.seq != last_seq + 1:
                    reason = f"entry {last_seq + 1} is missing"
                elif row.prev_hash != expected_prev:
                    reason = "prev_hash does not match the previous entry's hash"
                elif row.entry_hash != compute_entry_hash(
                        row.prev_hash, row.timestamp, row.actor, row.action, row.payload):
                    reason = "entry_hash does not match the entry's contents"
                if reason:
                    return ChainVerification(ok=False, entries_checked=checked,
                                             broken_seq=row.seq, reason=reason)
                checked += 1
                expected_prev = row.entry_hash
                last_seq = row.seq


async def read_entries(limit: int = 100, after_seq: int = 0) -> List[Dict[str, Any]]:
    """Entries in chain order, oldest first, starting after `after_seq`."""
    sf = get_session_factory()
    async with sf() as session:
        rows = (await session.execute(
            select(AuditChainEntry).where(AuditChainEntry.seq > after_seq)
            .order_by(AuditChainEntry.seq).limit(limit)
        )).scalars().all()
    return [
        {"seq": r.seq, "timestamp": r.timestamp, "actor": r.actor, "action": r.action,
         "payload": json.loads(r.payload), "prev_hash": r.prev_hash,
         "entry_hash": r.entry_hash}
        for r in rows
    ]
