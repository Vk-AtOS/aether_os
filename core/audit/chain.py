"""
AetherOS — tamper-evident audit chains.

Append-only, hash-linked ledger, one chain per organisation plus a platform chain for
events that belong to no organisation. An entry's chain is the top-level `org_id` of
its payload. Every entry stores the hash of the previous entry of its chain
(`prev_hash`) and its own hash (`entry_hash`) over a canonical serialisation of
(prev_hash, timestamp, actor, action, payload).

History: rows written before per-organisation chains existed form the frozen
`legacy` chain (ordered by `seq`, verifiable exactly as before). The first entry of
every new chain links to the legacy chain's last hash instead of to zeros, so each
new chain provably continues the old history; cutting the legacy tail breaks every
chain's first link.

`seq` is a global row id (gaps are possible); `chain_seq` is the gap-free position
inside a chain. Appends serialise per chain only. Signed checkpoints
(core/audit/checkpoints.py) let `verify_chain` start from the last checkpoint instead
of rescanning, and expose a shortened or rewritten tail.

This module deliberately exposes no update, delete or purge operation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import weakref
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from aether_os.core.audit import checkpoints
from aether_os.core.audit.checkpoints import AuditCheckpoint
from aether_os.core.db import Base, get_session_factory

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64
LEGACY_CHAIN = "legacy"        # rows written before per-organisation chains; frozen
PLATFORM_CHAIN = "_platform"   # events that belong to no organisation
_RESERVED = frozenset({LEGACY_CHAIN, PLATFORM_CHAIN})
# org_id values emitters use for "no organisation"; they go to the platform chain.
_NO_ORG = frozenset({"", "-", "unknown", "none", "null"})
# Appends are serialised per chain (see append()). The retry below is only the backstop
# for writers the locks cannot see (a second process on SQLite).
_APPEND_ATTEMPTS = 8
# Namespace for pg_advisory_xact_lock(int, int); the second key is hashtext(chain_id).
_PG_LOCK_NAMESPACE = 0x41455448  # "AETH"
_VERIFY_PAGE = 1000
_SHARED_LOCK = "*"
# Per event loop (a Lock cannot be shared across loops), one asyncio.Lock per chain.
# ponytail: one small lock per organisation kept for the process lifetime; fine at
# thousands of organisations, swap for an LRU if that ever grows unbounded.
_loop_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Dict[str, asyncio.Lock]]" = (
    weakref.WeakKeyDictionary())

ALL_CHAINS: Any = object()  # verify() default: structural check of every chain


def _local_lock(key: str) -> asyncio.Lock:
    """In-process lock per chain: on PostgreSQL it keeps waiting appends from each
    holding a pooled connection; on SQLite (one writer anyway) every chain shares one."""
    locks = _loop_locks.setdefault(asyncio.get_running_loop(), {})
    lock = locks.get(key)
    if lock is None:
        lock = locks[key] = asyncio.Lock()
    return lock


class AuditChainEntry(Base):
    __tablename__ = "audit_chain"
    __table_args__ = (
        # Gap-free position per chain, and the DB itself rejects a fork (two entries
        # after one parent) inside a chain.
        UniqueConstraint("chain_id", "chain_seq", name="uq_audit_chain_position"),
        UniqueConstraint("chain_id", "prev_hash", name="uq_audit_chain_prev"),
        Index("ix_audit_chain_chain_row", "chain_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chain_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # NULL on legacy rows
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # canonical JSON text
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


def _reject_mutation(_mapper, _connection, target) -> None:
    raise RuntimeError(f"audit_chain is append-only (entry seq={target.seq})")


event.listen(AuditChainEntry, "before_update", _reject_mutation)
event.listen(AuditChainEntry, "before_delete", _reject_mutation)


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    entries_checked: int
    broken_seq: Optional[int] = None   # global seq of the first broken entry
    reason: str = ""
    chain_id: Optional[str] = None
    head_seq: int = 0                  # chain position of the last good entry
    head_hash: Optional[str] = None
    checkpoint_seq: Optional[int] = None  # highest signed checkpoint compared with
    truncated: bool = False            # the chain is shorter than a signed checkpoint


def canonical_payload(payload: Dict[str, Any]) -> str:
    """Deterministic JSON text for a payload; this exact text is stored and hashed."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_entry_hash(prev_hash: str, timestamp: float, actor: str,
                       action: str, payload: str) -> str:
    """SHA-256 over the canonical serialisation of the five chained fields."""
    canonical = json.dumps([prev_hash, timestamp, actor, action, payload],
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def chain_id_for(org_id: Any) -> str:
    """The chain an event with this top-level org_id belongs to."""
    if org_id is None or str(org_id).strip().lower() in _NO_ORG:
        return PLATFORM_CHAIN
    cid = str(org_id).strip()
    if cid in _RESERVED or len(cid) > 64:
        raise ValueError(f"org_id {cid!r} cannot name an audit chain")
    return cid


def _payload_chain(payload_text: str) -> Optional[str]:
    try:
        return chain_id_for(json.loads(payload_text).get("org_id"))
    except (ValueError, AttributeError) as e:
        logger.warning("audit chain payload unreadable: %s", e)
        return None


def _position(row: AuditChainEntry) -> int:
    return row.seq if row.chain_id == LEGACY_CHAIN else row.chain_seq


def _position_column(cid: str):
    return AuditChainEntry.seq if cid == LEGACY_CHAIN else AuditChainEntry.chain_seq


async def _legacy_tail(session: AsyncSession) -> Tuple[int, str]:
    row = (await session.execute(
        select(AuditChainEntry.seq, AuditChainEntry.entry_hash)
        .where(AuditChainEntry.chain_id == LEGACY_CHAIN)
        .order_by(AuditChainEntry.seq.desc()).limit(1))).first()
    return (row.seq, row.entry_hash) if row else (0, GENESIS_HASH)


async def _tail(session: AsyncSession, cid: str) -> Optional[AuditChainEntry]:
    col = _position_column(cid)
    return (await session.execute(
        select(AuditChainEntry).where(AuditChainEntry.chain_id == cid)
        .order_by(col.desc()).limit(1))).scalars().first()


async def _at(session: AsyncSession, cid: str, pos: int) -> Optional[AuditChainEntry]:
    return (await session.execute(
        select(AuditChainEntry).where(AuditChainEntry.chain_id == cid,
                                      _position_column(cid) == pos))).scalars().first()


async def genesis() -> Dict[str, Any]:
    """What every per-organisation chain's first entry links to: the legacy tail."""
    async with get_session_factory()() as session:
        seq, entry_hash = await _legacy_tail(session)
    return {"legacy_tail_seq": seq, "legacy_tail_hash": entry_hash}


AlsoWrite = Callable[[AsyncSession, AuditChainEntry], Awaitable[None]]


async def append(actor: str, action: str, payload: Optional[Dict[str, Any]] = None,
                 timestamp: Optional[float] = None, *, also: Optional[AlsoWrite] = None
                 ) -> AuditChainEntry:
    """Append one entry to the chain of `payload["org_id"]` (platform chain if none).

    `also(session, entry)` runs inside the same transaction, so extra bookkeeping rows
    commit only together with the entry. Raises if the entry cannot be written —
    callers must not assume success.
    """
    payload = payload or {}
    cid = chain_id_for(payload.get("org_id"))
    payload_text = canonical_payload(payload)
    ts = time.time() if timestamp is None else float(timestamp)
    sf = get_session_factory()
    dialect = getattr(getattr(sf.kw.get("bind"), "dialect", None), "name", "")
    last_error: Optional[Exception] = None
    async with _local_lock(cid if dialect == "postgresql" else _SHARED_LOCK):
        for _ in range(_APPEND_ATTEMPTS):
            async with sf() as session:
                if dialect == "postgresql":
                    # Cross-process serialisation of this chain only: held until the
                    # transaction ends, so no other writer can read the same tail.
                    await session.execute(text("SELECT pg_advisory_xact_lock(:ns, hashtext(:c))"),
                                          {"ns": _PG_LOCK_NAMESPACE, "c": cid})
                tail = await _tail(session, cid)
                prev_hash = tail.entry_hash if tail else (await _legacy_tail(session))[1]
                entry = AuditChainEntry(
                    chain_id=cid, chain_seq=(tail.chain_seq + 1) if tail else 1,
                    timestamp=ts, actor=actor, action=action, payload=payload_text,
                    prev_hash=prev_hash,
                    entry_hash=compute_entry_hash(prev_hash, ts, actor, action, payload_text),
                )
                session.add(entry)
                if also is not None:
                    await also(session, entry)
                try:
                    await session.commit()
                    return entry
                except IntegrityError as e:
                    # Another writer took this position; re-read the tail and retry.
                    last_error = e
                    await session.rollback()
    raise RuntimeError(f"audit chain append lost {_APPEND_ATTEMPTS} races") from last_error


def _check(row: AuditChainEntry, cid: str, want: int, prev: str) -> str:
    if _position(row) != want:
        return f"entry {want} is missing"
    if row.prev_hash != prev:
        return "prev_hash does not match the previous entry's hash"
    if row.entry_hash != compute_entry_hash(
            row.prev_hash, row.timestamp, row.actor, row.action, row.payload):
        return "entry_hash does not match the entry's contents"
    if cid != LEGACY_CHAIN and _payload_chain(row.payload) != cid:
        return "entry's org_id does not belong to this chain"
    return ""


async def _walk(session: AsyncSession, cid: str, pos: int, prev: str,
                anchors: Dict[int, str]) -> ChainVerification:
    """Check every entry after position `pos`, whose predecessor hash must be `prev`."""
    col = _position_column(cid)
    checked = 0
    while True:
        rows = (await session.execute(
            select(AuditChainEntry).where(AuditChainEntry.chain_id == cid, col > pos)
            .order_by(col).limit(_VERIFY_PAGE))).scalars().all()
        if not rows:
            return ChainVerification(ok=True, entries_checked=checked, chain_id=cid,
                                     head_seq=pos, head_hash=prev if pos else None)
        for row in rows:
            reason = _check(row, cid, pos + 1, prev)
            if not reason and anchors.get(pos + 1, row.entry_hash) != row.entry_hash:
                reason = "entry differs from a signed checkpoint (the chain was rewritten)"
            if reason:
                return ChainVerification(ok=False, entries_checked=checked, broken_seq=row.seq,
                                         reason=reason, chain_id=cid, head_seq=pos,
                                         head_hash=prev if pos else None)
            checked += 1
            pos, prev = pos + 1, row.entry_hash


def _failed(cid: str, reason: str, **kw: Any) -> ChainVerification:
    return ChainVerification(ok=False, entries_checked=0, reason=reason, chain_id=cid, **kw)


async def verify_chain(cid: str, *, full: bool = False,
                       checkpoint: Optional[Dict[str, Any]] = None) -> ChainVerification:
    """Verify one chain against its signed checkpoints (and `checkpoint`, a copy the
    customer kept, if given).

    Incremental by default: starts from the newest signed checkpoint, whose entry must
    still carry the signed hash, and checks only what came after it. `full=True`
    rescans from the first entry and compares every stored checkpoint on the way.
    Reports truncation when the chain is shorter than any signed checkpoint.
    """
    async with get_session_factory()() as session:
        q = (select(AuditCheckpoint).where(AuditCheckpoint.chain_id == cid)
             .order_by(AuditCheckpoint.chain_seq.desc()))
        stored = [checkpoints.to_dict(r) for r in
                  (await session.execute(q if full else q.limit(1))).scalars().all()]
        anchors: Dict[int, str] = {}
        for cp in stored + ([checkpoint] if checkpoint else []):
            if cp.get("chain_id") != cid or not checkpoints.signature_ok(cp):
                return _failed(cid, "a checkpoint for this chain is not validly signed")
            if anchors.setdefault(int(cp["chain_seq"]), cp["head_hash"]) != cp["head_hash"]:
                return _failed(cid, "signed checkpoints disagree about the same entry")
        top = max(anchors, default=0)
        tail = await _tail(session, cid)
        head = _position(tail) if tail else 0
        if head < top:
            return _failed(cid, f"tail truncated: the chain ends at entry {head} but a signed "
                                f"checkpoint covers entry {top}", head_seq=head,
                           checkpoint_seq=top, truncated=True)
        pos = 0
        prev = GENESIS_HASH if cid == LEGACY_CHAIN else (await _legacy_tail(session))[1]
        if not full and stored:
            pos, prev = stored[0]["chain_seq"], stored[0]["head_hash"]
        # Checkpoints at or before the starting point are compared directly.
        for at_pos in sorted(p for p in anchors if p <= pos):
            row = await _at(session, cid, at_pos)
            if row is None or row.entry_hash != anchors[at_pos] or row.entry_hash != compute_entry_hash(
                    row.prev_hash, row.timestamp, row.actor, row.action, row.payload):
                return _failed(cid, f"entry {at_pos} differs from a signed checkpoint "
                                    "(the chain was rewritten)",
                               broken_seq=row.seq if row else None, checkpoint_seq=top)
        result = await _walk(session, cid, pos, prev, anchors)
    return replace(result, checkpoint_seq=top or None)


async def chain_ids() -> List[str]:
    """Every chain that has entries, legacy first.

    ponytail: DISTINCT over the (chain_id, seq) index, a full index scan; keep a heads
    table if the periodic anchor run ever gets slow.
    """
    async with get_session_factory()() as session:
        ids = (await session.execute(select(AuditChainEntry.chain_id).distinct())).scalars().all()
    return sorted(ids, key=lambda c: (c != LEGACY_CHAIN, c))


async def verify(org_id: Any = ALL_CHAINS, *, full: bool = False,
                 checkpoint: Optional[Dict[str, Any]] = None) -> ChainVerification:
    """verify(org_id): one organisation's chain (None = the platform chain), against
    its signed checkpoints, incrementally unless `full`.

    verify() with no argument: a full structural walk of every chain, legacy included
    (links, hashes, positions, org membership; signed checkpoints are not consulted).
    """
    if org_id is not ALL_CHAINS:
        return await verify_chain(chain_id_for(org_id), full=full, checkpoint=checkpoint)
    total = 0
    async with get_session_factory()() as session:
        genesis_hash = (await _legacy_tail(session))[1]
        for cid in await chain_ids():
            start = GENESIS_HASH if cid == LEGACY_CHAIN else genesis_hash
            result = await _walk(session, cid, 0, start, {})
            total += result.entries_checked
            if not result.ok:
                return replace(result, entries_checked=total)
    return ChainVerification(ok=True, entries_checked=total)


def _as_dict(r: AuditChainEntry) -> Dict[str, Any]:
    return {"seq": r.seq, "chain_id": r.chain_id, "chain_seq": r.chain_seq,
            "timestamp": r.timestamp, "actor": r.actor, "action": r.action,
            "payload": json.loads(r.payload), "prev_hash": r.prev_hash,
            "entry_hash": r.entry_hash}


async def read_entries(limit: int = 100, after_seq: int = 0) -> List[Dict[str, Any]]:
    """Entries of all chains in global seq order, oldest first, starting after `after_seq`."""
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(AuditChainEntry).where(AuditChainEntry.seq > after_seq)
            .order_by(AuditChainEntry.seq).limit(limit)
        )).scalars().all()
    return [_as_dict(r) for r in rows]


async def entry_link(seq: int) -> Optional[Dict[str, Any]]:
    """One entry (by global seq) with the hash of the entry before it *in its own
    chain*, and whether the link and the entry's own hash hold. None if absent."""
    async with get_session_factory()() as session:
        row = await session.get(AuditChainEntry, seq)
        if row is None:
            return None
        pos = _position(row)
        prev = await _at(session, row.chain_id, pos - 1) if pos > 1 else None
        if prev is not None:
            expected: Optional[str] = prev.entry_hash
        elif pos == 1:
            expected = GENESIS_HASH if row.chain_id == LEGACY_CHAIN else (await _legacy_tail(session))[1]
        else:
            expected = None  # the previous entry is missing
    return {**_as_dict(row),
            "previous": {"seq": prev.seq if prev else None, "entry_hash": expected},
            "link_ok": expected == row.prev_hash,
            "hash_ok": row.entry_hash == compute_entry_hash(
                row.prev_hash, row.timestamp, row.actor, row.action, row.payload)}
