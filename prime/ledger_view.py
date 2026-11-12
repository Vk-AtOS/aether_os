"""Prime — read-only views of the ledger (core/audit/chain.py), one organisation at a time.

An entry belongs to an organisation when its payload carries that `org_id` at the
top level. Nothing here writes, and nothing is added to what the ledger holds.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import or_, select

from aether_os.core.audit.chain import GENESIS_HASH, AuditChainEntry, compute_entry_hash
from aether_os.core.db import get_session_factory

_BATCH = 500


def _entry(r: AuditChainEntry) -> Dict[str, Any]:
    return {"seq": r.seq, "timestamp": r.timestamp, "actor": r.actor, "action": r.action,
            "payload": json.loads(r.payload), "prev_hash": r.prev_hash,
            "entry_hash": r.entry_hash}


def _org_marker(org_id: str) -> str:
    # Payloads are stored as canonical JSON (sorted keys, no spaces), so this text is
    # how a top-level or nested org_id appears; the parsed payload is checked after.
    return f'"org_id":{json.dumps(org_id)}'


async def browse(org_id: str, *, actor: Optional[str] = None, action_prefix: Optional[str] = None,
                 since: Optional[float] = None, until: Optional[float] = None,
                 before_seq: Optional[int] = None, limit: int = 50) -> Dict[str, Any]:
    """Newest first. `next_before` is the cursor for the following page, or None."""
    conds = [AuditChainEntry.payload.contains(_org_marker(org_id), autoescape=True)]
    if actor:
        conds.append(AuditChainEntry.actor == actor)
    if action_prefix:
        conds.append(AuditChainEntry.action.startswith(action_prefix, autoescape=True))
    if since is not None:
        conds.append(AuditChainEntry.timestamp >= since)
    if until is not None:
        conds.append(AuditChainEntry.timestamp <= until)
    found: List[Dict[str, Any]] = []
    cursor = before_seq
    async with get_session_factory()() as session:
        while len(found) <= limit:
            page = [AuditChainEntry.seq < cursor] if cursor is not None else []
            rows = (await session.execute(
                select(AuditChainEntry).where(*conds, *page)
                .order_by(AuditChainEntry.seq.desc()).limit(_BATCH))).scalars().all()
            if not rows:
                break
            cursor = rows[-1].seq
            found += [e for e in map(_entry, rows) if e["payload"].get("org_id") == org_id]
    more = len(found) > limit
    found = found[:limit]
    return {"entries": found, "next_before": found[-1]["seq"] if more else None}


async def entry(org_id: str, seq: int) -> Optional[Dict[str, Any]]:
    """One entry with its link to the entry before it, or None if it is not this org's."""
    async with get_session_factory()() as session:
        row = await session.get(AuditChainEntry, seq)
        if row is None or json.loads(row.payload).get("org_id") != org_id:
            return None
        prev = await session.get(AuditChainEntry, seq - 1) if seq > 1 else None
    # The previous entry may belong to anyone: only its position and hash are returned.
    prev_hash = prev.entry_hash if prev else (GENESIS_HASH if seq == 1 else None)
    return {
        **_entry(row),
        "previous": {"seq": seq - 1 if seq > 1 else None, "entry_hash": prev_hash},
        "link_ok": prev_hash == row.prev_hash,
        "hash_ok": row.entry_hash == compute_entry_hash(
            row.prev_hash, row.timestamp, row.actor, row.action, row.payload),
    }


async def by_delegation(delegation_ids: Iterable[str], per_delegation: int = 50
                        ) -> Dict[str, List[Dict[str, Any]]]:
    """Prime ledger entries that name each delegation, newest first.

    ponytail: text match over prime.* entries, newest 2,000. Add an indexed
    delegation column to the ledger if one company's volume outgrows that.
    """
    ids = list(delegation_ids)
    out: Dict[str, List[Dict[str, Any]]] = {i: [] for i in ids}
    if not ids:
        return out
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(AuditChainEntry).where(
                AuditChainEntry.action.startswith("prime."),
                or_(*[AuditChainEntry.payload.contains(f'"delegation_id":"{i}"') for i in ids]))
            .order_by(AuditChainEntry.seq.desc()).limit(2000))).scalars().all()
    for e in map(_entry, rows):
        bucket = out.get(e["payload"].get("delegation_id"))
        if bucket is not None and len(bucket) < per_delegation:
            bucket.append({k: e[k] for k in ("seq", "timestamp", "actor", "action", "payload")})
    return out
