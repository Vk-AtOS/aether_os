"""Prime — read-only views of the ledger (core/audit/chain.py), one organisation at a time.

Each organisation has its own chain (`chain_id` = its org_id). Entries written before
per-organisation chains sit in the frozen `legacy` chain; one of those belongs to an
organisation when its payload carries that `org_id` at the top level. Nothing here
writes. Emails/IPs are shown through the erasure overlay (core/audit/subjects.py).
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import and_, or_, select

from aether_os.core.audit import chain, subjects
from aether_os.core.audit.chain import AuditChainEntry
from aether_os.core.db import get_session_factory

_BATCH = 500


def _entry(r: AuditChainEntry) -> Dict[str, Any]:
    return {"seq": r.seq, "chain_seq": r.chain_seq, "timestamp": r.timestamp, "actor": r.actor,
            "action": r.action, "payload": json.loads(r.payload), "prev_hash": r.prev_hash,
            "entry_hash": r.entry_hash}


def _org_marker(org_id: str) -> str:
    # Payloads are stored as canonical JSON (sorted keys, no spaces), so this text is
    # how a top-level or nested org_id appears; the parsed payload is checked after.
    return f'"org_id":{json.dumps(org_id)}'


def _belongs(org_id: str):
    """SQL condition: this organisation's chain, or a legacy entry that names it."""
    return or_(AuditChainEntry.chain_id == chain.chain_id_for(org_id),
               and_(AuditChainEntry.chain_id == chain.LEGACY_CHAIN,
                    AuditChainEntry.payload.contains(_org_marker(org_id), autoescape=True)))


async def browse(org_id: str, *, actor: Optional[str] = None, action_prefix: Optional[str] = None,
                 since: Optional[float] = None, until: Optional[float] = None,
                 before_seq: Optional[int] = None, limit: int = 50) -> Dict[str, Any]:
    """Newest first. `next_before` is the cursor for the following page, or None."""
    conds = [_belongs(org_id)]
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
    return {"entries": await subjects.overlay_entries(org_id, found),
            "next_before": found[-1]["seq"] if more else None}


async def entry(org_id: str, seq: int) -> Optional[Dict[str, Any]]:
    """One entry with its link to the entry before it in the same chain, or None if it
    is not this org's. The previous entry is always this org's own (or the genesis)."""
    found = await chain.entry_link(seq)
    if found is None or found["payload"].get("org_id") != org_id:
        return None
    if found["chain_id"] not in (chain.chain_id_for(org_id), chain.LEGACY_CHAIN):
        return None
    # In the legacy chain the predecessor may belong to anyone: only its seq and hash
    # are in "previous", never its content.
    return (await subjects.overlay_entries(org_id, [found]))[0]


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


async def by_request(org_id: str, request_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Prime ledger entries of one approval request, oldest first (the request's timeline).

    Matches the request id in the payload text, then confirms org and id on the parsed
    payload, so another organisation's entry can never be returned.
    """
    async with get_session_factory()() as session:
        rows = (await session.execute(
            select(AuditChainEntry).where(
                AuditChainEntry.action.startswith("prime."),
                AuditChainEntry.payload.contains(f'"request_id":"{request_id}"'))
            .order_by(AuditChainEntry.seq.asc()).limit(limit * 2))).scalars().all()
    out = [e for e in map(_entry, rows)
           if e["payload"].get("request_id") == request_id and e["payload"].get("org_id") == org_id]
    return out[:limit]
