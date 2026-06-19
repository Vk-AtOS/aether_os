"""
AetherOS — Run Service

Business logic extracted from gateway/routers/factory_runs_router.py.
All direct DB queries live here; the router delegates to these functions.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_run_by_id(
    sess: AsyncSession, run_id: str, org_id: str
) -> Optional[Any]:
    """Return a Run row if it belongs to the given org, else None."""
    from aether_os.core.models import Run

    return (await sess.execute(
        select(Run).where(Run.id == run_id, Run.org_id == org_id)
    )).scalar_one_or_none()


async def get_test_report(
    sess: AsyncSession, run_id: str, org_id: str
) -> Optional[str]:
    """
    Return the raw self_test_report JSON string for a run, or None if not found.
    Caller raises 404 if None.
    """
    from aether_os.core.models import Run

    run = (await sess.execute(
        select(Run).where(Run.id == run_id, Run.org_id == org_id)
    )).scalar_one_or_none()

    if not run:
        return None
    return run.self_test_report


async def enrich_runs_with_quality(
    sess: AsyncSession, items: List[Dict[str, Any]]
) -> None:
    """
    Best-effort enrichment: attach quality_score to each item dict in-place.
    Missing scores are left as None. Does not raise on failure.
    """
    from aether_os.core.models import Run

    run_ids = [r.get("id") for r in items if r.get("id")]
    if not run_ids:
        return

    try:
        rows = (await sess.execute(
            select(Run.id, Run.quality_score).where(Run.id.in_(run_ids))
        )).all()
        qs_map = {rid: qs for rid, qs in rows if qs is not None}
        for item in items:
            item.setdefault("quality_score", qs_map.get(item.get("id")))
    except Exception as exc:
        logger.debug("quality_score enrichment failed: %s", exc)


async def get_phase_completions(
    sess: AsyncSession, run_id: str
) -> List[Any]:
    """Return all non-pipeline phase completions for a run, ordered by time."""
    from aether_os.core.models import PhaseCompletion

    return (await sess.execute(
        select(PhaseCompletion.phase_name, PhaseCompletion.status, PhaseCompletion.updated_at)
        .where(PhaseCompletion.run_id == run_id, PhaseCompletion.phase_name != "pipeline")
        .order_by(PhaseCompletion.updated_at.asc())
    )).all()


async def get_explicit_events(
    sess: AsyncSession, run_id: str
) -> List[Any]:
    """Return explicit Event rows for a run, ordered by timestamp."""
    from aether_os.core.models import Event

    return (await sess.execute(
        select(Event.agent, Event.action, Event.detail, Event.timestamp)
        .where(Event.run_id == run_id)
        .order_by(Event.timestamp.asc())
    )).all()


async def get_run_priority_and_live_url(
    sess: AsyncSession, run_id: str, org_id: str
) -> Tuple[str, Optional[str]]:
    """Return (priority, live_url) for a run. Defaults to ('normal', None)."""
    from aether_os.core.models import RunMetadata, Run

    priority = "normal"
    live_url = None

    rm_row = (await sess.execute(
        select(RunMetadata.priority).where(RunMetadata.run_id == run_id)
    )).scalar_one_or_none()
    if rm_row:
        priority = rm_row

    run_row = (await sess.execute(
        select(Run.live_url).where(Run.id == run_id, Run.org_id == org_id)
    )).scalar_one_or_none()
    if run_row:
        live_url = run_row

    return priority, live_url


async def get_run_snapshots(
    sess: AsyncSession, run_id: str, org_id: str
) -> Tuple[bool, List[Any]]:
    """
    Return (run_found, snapshots) for a run.
    run_found is False if the run doesn't belong to the org.
    """
    from aether_os.core.models import Run, Snapshot

    run = await sess.get(Run, run_id)
    if not run or run.org_id != org_id:
        return False, []

    rows = (await sess.execute(
        select(Snapshot)
        .where(Snapshot.run_id == run_id)
        .order_by(Snapshot.created_at.desc())
    )).scalars().all()
    return True, list(rows)


async def get_run_snapshot_detail(
    sess: AsyncSession, run_id: str, snapshot_id: str, org_id: str
) -> Tuple[bool, Optional[Any]]:
    """
    Return (run_found, snapshot_or_none).
    run_found is False if the run or snapshot doesn't belong to the org.
    """
    from aether_os.core.models import Run, Snapshot

    run = await sess.get(Run, run_id)
    if not run or run.org_id != org_id:
        return False, None

    snap = await sess.get(Snapshot, snapshot_id)
    if not snap or snap.run_id != run_id:
        return True, None

    return True, snap


async def upsert_run_priority(
    sess: AsyncSession, run_id: str, priority: str
) -> None:
    """Set the priority for a run. Caller must commit."""
    from aether_os.core.models import RunMetadata

    existing = await sess.get(RunMetadata, run_id)
    if existing:
        existing.priority = priority
        existing.updated_at = time.time()
    else:
        sess.add(RunMetadata(run_id=run_id, priority=priority, updated_at=time.time()))


async def get_org_for_run(
    sess: AsyncSession, org_id: str
) -> Optional[Any]:
    """Return the Organisation row, or None."""
    from aether_os.core.models import Organisation

    return (await sess.execute(
        select(Organisation).where(Organisation.id == org_id)
    )).scalar_one_or_none()


async def increment_trial_runs(
    sess: AsyncSession, org_id: str
) -> bool:
    """
    Atomically increment trial_runs_used if under the limit.
    Returns True if successful, False if limit already reached.
    Caller must commit.
    """
    from aether_os.core.models import Organisation
    from sqlalchemy import update as _sa_upd

    upd = await sess.execute(
        _sa_upd(Organisation)
        .where(Organisation.id == org_id)
        .where(Organisation.trial_runs_used < Organisation.trial_runs_limit)
        .values(trial_runs_used=Organisation.trial_runs_used + 1)
    )
    return upd.rowcount > 0


async def get_run_for_portal(
    sess: AsyncSession, run_id: str, org_id: str
) -> Optional[Any]:
    """Return the Run row for portal use (includes council_delivery, quality_score)."""
    from aether_os.core.models import Run

    return (await sess.execute(
        select(Run).where(Run.id == run_id, Run.org_id == org_id)
    )).scalar_one_or_none()


async def get_run_name_and_domain(
    sess: AsyncSession, run_id: str, org_id: str
) -> Tuple[str, str]:
    """
    Return (project_name, domain) for a run. Defaults to ("", "general").
    Used for compliance scans that need context without blocking on missing data.
    """
    from aether_os.core.models import Run

    try:
        run = (await sess.execute(
            select(Run).where(Run.id == run_id, Run.org_id == org_id)
        )).scalar_one_or_none()
        if run:
            return getattr(run, "project_name", "") or "", getattr(run, "domain", "general") or "general"
    except Exception as exc:
        logger.debug("get_run_name_and_domain failed for run %s: %s", run_id, exc)
    return "", "general"
