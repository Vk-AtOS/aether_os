"""Prime learning loop (KAN-229): record each use of a learned item, then whether it helped; retire what keeps failing.

    record_use(org, kind, item_ids, scope, ref)        an item was put into a prompt / a fix was replayed
    record_outcome(org, kind, helped, ...)             the outcome of the pending uses that match
    retired_ids(org, kind)                             items that must not be put into a prompt any more
    set_retired(org, kind, item_id, retired, by)       an admin retires or restores one

Best effort: recording never raises into a build or an approval (a failure is logged and the caller goes on).
Every query filters by org_id.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Set

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from aether_os.core.db import get_session_factory
from aether_os.prime.learning.models import LearningBuildOutcome, LearningItemState, LearningUse

logger = logging.getLogger(__name__)

KINDS = ("correction", "golden", "fix")
RETIRE_AFTER = 3            # outcomes in a row that did not help -> retired automatically
MAX_ITEMS = 10              # items recorded per use call (prompts take 2-5)
PENDING_FOR = timedelta(days=7)   # an older pending use is not settled by a later outcome


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)   # naive UTC, like the columns


def _ok(org_id: Optional[str], kind: str) -> bool:
    return bool(org_id) and kind in KINDS


async def record_use(org_id: Optional[str], kind: str, item_ids: Iterable[str], scope: str = "",
                     ref: Optional[str] = None) -> int:
    """One pending use per item. Returns how many were recorded (0 on any failure)."""
    ids = [str(i)[:64] for i in dict.fromkeys(item_ids) if i][:MAX_ITEMS]
    if not _ok(org_id, kind) or not ids:
        return 0
    try:
        async with get_session_factory()() as s:
            s.add_all([LearningUse(org_id=org_id, kind=kind, item_id=i, scope=scope[:200],
                                   ref=(ref or None) and str(ref)[:64], used_at=_now()) for i in ids])
            await s.commit()
        return len(ids)
    except Exception as e:
        logger.warning("learning: use of %d %s item(s) not recorded: %s", len(ids), kind, e)
        return 0


async def record_outcome(org_id: Optional[str], kind: str, helped: bool, *, ref: Optional[str] = None,
                         item_ids: Optional[Iterable[str]] = None, scopes: Optional[Iterable[str]] = None) -> int:
    """Settle this org's pending uses of `kind` that match every filter given (ref, items, scopes) and are younger
    than PENDING_FOR. Each settled item's failure streak moves; at RETIRE_AFTER it is retired. Returns uses settled."""
    if not _ok(org_id, kind) or (ref is None and item_ids is None and scopes is None):
        return 0
    try:
        now = _now()
        conds = [LearningUse.org_id == org_id, LearningUse.kind == kind, LearningUse.helped.is_(None),
                 LearningUse.used_at >= now - PENDING_FOR]
        if ref is not None:
            conds.append(LearningUse.ref == str(ref)[:64])
        if item_ids is not None:
            conds.append(LearningUse.item_id.in_([str(i)[:64] for i in item_ids]))
        if scopes is not None:
            conds.append(LearningUse.scope.in_([str(x)[:200] for x in scopes]))
        async with get_session_factory()() as s:
            rows = (await s.execute(select(LearningUse).where(*conds))).scalars().all()
            if not rows:
                return 0
            await s.execute(update(LearningUse).where(LearningUse.id.in_([r.id for r in rows]))
                            .values(helped=helped, settled_at=now))
            for item in dict.fromkeys(r.item_id for r in rows):
                await _move_streak(s, org_id, kind, item, helped, now)
            await s.commit()
        return len(rows)
    except Exception as e:
        logger.warning("learning: %s outcome not recorded: %s", kind, e)
        return 0


async def _state(s, org_id: str, kind: str, item_id: str) -> LearningItemState:
    row = (await s.execute(select(LearningItemState).where(
        LearningItemState.org_id == org_id, LearningItemState.kind == kind,
        LearningItemState.item_id == item_id))).scalar_one_or_none()
    if row is None:
        row = LearningItemState(org_id=org_id, kind=kind, item_id=item_id, failures=0, retired=False)
        s.add(row)
    return row


async def _move_streak(s, org_id: str, kind: str, item_id: str, helped: bool, now: datetime) -> None:
    row = await _state(s, org_id, kind, item_id)
    row.failures = 0 if helped else (row.failures or 0) + 1
    if not helped and row.failures >= RETIRE_AFTER and not row.retired:
        row.retired, row.retired_at, row.retired_by = True, now, "prime"
        row.retired_reason = f"did not help {row.failures} times in a row"
        logger.info("learning: %s item %s retired for org %s after %d failures", kind, item_id[:12], org_id,
                    row.failures)


async def retired_ids(org_id: Optional[str], kind: str) -> Set[str]:
    """Items of this kind retired in this org. On a read failure: empty (logged), so prompts still get built."""
    if not _ok(org_id, kind):
        return set()
    try:
        async with get_session_factory()() as s:
            return set((await s.execute(select(LearningItemState.item_id).where(
                LearningItemState.org_id == org_id, LearningItemState.kind == kind,
                LearningItemState.retired.is_(True)))).scalars().all())
    except Exception as e:
        logger.warning("learning: retired %s items not read: %s", kind, e)
        return set()


async def set_retired(org_id: str, kind: str, item_id: str, retired: bool, by: str) -> dict:
    """Retire or restore one item (an admin). A restore starts a fresh failure streak."""
    if not _ok(org_id, kind):
        raise ValueError("unknown kind")
    async with get_session_factory()() as s:
        row = await _state(s, org_id, kind, item_id[:64])
        row.retired = retired
        if not retired:
            row.failures = 0
        row.retired_at = _now() if retired else None
        row.retired_by = by[:255] if retired else None
        row.retired_reason = "retired by an admin" if retired else None
        await s.commit()
        return {"kind": kind, "id": row.item_id, "retired": row.retired}


async def record_build(org_id: Optional[str], run_id: Optional[str], built: bool, first_pass: bool,
                       rounds: int) -> bool:
    """The first build of a run: first-pass trend, and whether it built settles that run's golden examples."""
    if not org_id or not run_id:
        return False
    try:
        async with get_session_factory()() as s:
            s.add(LearningBuildOutcome(org_id=org_id, run_id=run_id, built=bool(built), first_pass=bool(first_pass),
                                       rounds=int(rounds or 0), created_at=_now()))
            await s.commit()
    except IntegrityError:
        return False                      # a later rebuild of the same run: the first one counts
    except Exception as e:
        logger.warning("learning: build outcome of run %s not recorded: %s", run_id, e)
        return False
    await record_outcome(org_id, "golden", bool(built), ref=run_id)
    return True
