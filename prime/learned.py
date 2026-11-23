"""Prime — what Prime learned about a person (KAN-228): the ONLY module that reads or writes prime_learned_items.

Every row belongs to one organisation AND one person, and every query here filters on both. Writes (`record`) and
reads for Prime's own use (`usable`) call consent.allowed() first. The person's own view and export first delete
whatever consent no longer covers (`_drop_withdrawn`, which also calls allowed()), so nothing stored is hidden from
them and nothing withdrawn is shown or used. Personal data is pseudonymised before storage (prime/detail.py labels),
and credentials are masked, so text that later feeds a prompt carries labels, not names or e-mail addresses.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, func, select

from aether_os.core.audit import chain as audit_chain
from aether_os.core.db import get_session_factory
from aether_os.prime import consent
from aether_os.prime.corrections import pseudonymise
from aether_os.prime.models import PrimeConsent, PrimeLearnedItem, PrimeLearningSettings

logger = logging.getLogger(__name__)

NEWEST = 10          # newest items shown per person on the screen
USABLE_MAX = 50      # items handed to Prime per call
SUMMARY_CAP = 1000


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _item(r: PrimeLearnedItem) -> Dict[str, Any]:
    return {"id": r.id, "source": r.source, "kind": r.kind, "summary": r.summary, "data": r.data,
            "learned_at": r.learned_at.isoformat()}


async def record(org_id: str, user_id: str, source: str, kind: str, summary: str,
                 data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Store one learned item; None (nothing stored) unless the person consented to this source now."""
    if not await consent.allowed(org_id, user_id, source):
        return None
    row = PrimeLearnedItem(
        org_id=org_id, user_id=user_id, source=source, kind=kind[:64],
        summary=str(await pseudonymise(org_id, str(summary)[:SUMMARY_CAP]))[:SUMMARY_CAP],
        data=await pseudonymise(org_id, data) if data else None, learned_at=_now())
    async with get_session_factory()() as session:
        session.add(row)
        await session.commit()
    return row.id


async def usable(org_id: str, user_id: str, source: str, limit: int = USABLE_MAX) -> List[Dict[str, Any]]:
    """What Prime may use for this person from this source: nothing unless consent holds now."""
    if not await consent.allowed(org_id, user_id, source):
        return []
    async with get_session_factory()() as session:
        rows = (await session.execute(select(PrimeLearnedItem).where(
            PrimeLearnedItem.org_id == org_id, PrimeLearnedItem.user_id == user_id,
            PrimeLearnedItem.source == source).order_by(PrimeLearnedItem.learned_at.desc())
            .limit(max(1, min(limit, USABLE_MAX))))).scalars().all()
    return [_item(r) for r in rows]


async def _delete(org_id: str, user_id: Optional[str], sources: Optional[Iterable[str]] = None,
                  before: Optional[datetime] = None) -> int:
    conds = [PrimeLearnedItem.org_id == org_id]
    if user_id is not None:
        conds.append(PrimeLearnedItem.user_id == user_id)
    if sources is not None:
        conds.append(PrimeLearnedItem.source.in_(list(sources)))
    if before is not None:
        conds.append(PrimeLearnedItem.learned_at < before)
    async with get_session_factory()() as session:
        n = (await session.execute(delete(PrimeLearnedItem).where(*conds))).rowcount
        await session.commit()
    return n or 0


async def _drop_withdrawn(org_id: str, user_id: str) -> int:
    """Delete this person's items from every source consent no longer covers. Returns how many."""
    async with get_session_factory()() as session:
        held = (await session.execute(select(PrimeLearnedItem.source).distinct().where(
            PrimeLearnedItem.org_id == org_id, PrimeLearnedItem.user_id == user_id))).scalars().all()
    gone = [s for s in held if not await consent.allowed(org_id, user_id, s)]
    return await _delete(org_id, user_id, gone) if gone else 0


async def summary(org_id: str, user_id: str) -> Dict[str, Any]:
    """Counts per source and the newest items, for the person's own screen."""
    await _drop_withdrawn(org_id, user_id)
    async with get_session_factory()() as session:
        mine = (PrimeLearnedItem.org_id == org_id, PrimeLearnedItem.user_id == user_id)
        counts = dict((await session.execute(select(PrimeLearnedItem.source, func.count()).where(*mine)
                                             .group_by(PrimeLearnedItem.source))).all())
        newest = (await session.execute(select(PrimeLearnedItem).where(*mine)
                                        .order_by(PrimeLearnedItem.learned_at.desc()).limit(NEWEST))).scalars().all()
    return {"counts": {s: int(counts.get(s, 0)) for s in consent.SOURCES}, "newest": [_item(r) for r in newest]}


async def export(org_id: str, user_id: str) -> Dict[str, Any]:
    """Everything stored about this person: consent record and every learned item. Ledgered (who, how many)."""
    await _drop_withdrawn(org_id, user_id)
    async with get_session_factory()() as session:
        rows = (await session.execute(select(PrimeLearnedItem).where(
            PrimeLearnedItem.org_id == org_id, PrimeLearnedItem.user_id == user_id)
            .order_by(PrimeLearnedItem.learned_at))).scalars().all()
    await audit_chain.append(actor=user_id, action="prime.data.export",
                             payload={"org_id": org_id, "user_id": user_id, "items": len(rows)})
    return {"exported_at": _now().isoformat(), "org_id": org_id, "user_id": user_id,
            "consent": await consent.state(org_id, user_id), "learned": [_item(r) for r in rows]}


async def erase(org_id: str, user_id: str, by: str, source: Optional[str] = None) -> int:
    """The person erases what was learned from one source, or from all (source None). Ledgered."""
    if by != user_id:
        raise PermissionError("only the person can erase their own learned data")
    if source is not None and source not in consent.SOURCES:
        raise ValueError(f"unknown source {source!r}")
    sources = [source] if source else list(consent.SOURCES)
    n = await _delete(org_id, user_id, sources)
    await audit_chain.append(actor=by, action="prime.data.erase",
                             payload={"org_id": org_id, "user_id": user_id, "sources": sources, "items": n})
    return n


async def withdraw(org_id: str, user_id: str, sources: List[str]) -> int:
    """Delete what was learned from sources whose consent was just withdrawn (consent.set_switch)."""
    return await _delete(org_id, user_id, sources) if sources else 0


async def orgs_holding() -> List[str]:
    """Organisations that have learned items (for the purge job)."""
    async with get_session_factory()() as session:
        return list((await session.execute(select(PrimeLearnedItem.org_id).distinct())).scalars().all())


async def expire(org_id: str, before: datetime) -> int:
    """Delete the organisation's items learned before `before` (retention)."""
    return await _delete(org_id, None, before=before)


async def drop_withdrawn_everywhere(limit: int) -> Dict[str, int]:
    """Delete items of every (person, source) whose consent no longer holds, at most `limit` groups.
    Returns {org_id: items deleted}."""
    async with get_session_factory()() as session:
        groups = (await session.execute(select(PrimeLearnedItem.org_id, PrimeLearnedItem.user_id,
                                               PrimeLearnedItem.source).distinct().limit(limit))).all()
    out: Dict[str, int] = {}
    for org_id, user_id, source in groups:
        if not await consent.allowed(org_id, user_id, source):
            n = await _delete(org_id, user_id, [source])
            if n:
                out[org_id] = out.get(org_id, 0) + n
    return out


async def erase_person(org_id: str, user_id: str) -> int:
    """Account deletion (core/audit/deletion.py): learned items and consent records of the person."""
    n = await _delete(org_id, user_id)
    async with get_session_factory()() as session:
        await session.execute(delete(PrimeConsent).where(PrimeConsent.org_id == org_id,
                                                         PrimeConsent.user_id == user_id))
        await session.commit()
    return n


async def erase_org(org_id: str) -> int:
    """Organisation deletion: every learned item, consent record and setting of the organisation."""
    n = await _delete(org_id, None)
    async with get_session_factory()() as session:
        await session.execute(delete(PrimeConsent).where(PrimeConsent.org_id == org_id))
        await session.execute(delete(PrimeLearningSettings).where(PrimeLearningSettings.org_id == org_id))
        await session.commit()
    return n
