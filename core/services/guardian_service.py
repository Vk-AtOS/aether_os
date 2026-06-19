"""
AetherOS — Guardian Service

Business logic extracted from gateway/routers/guardian_router.py.
All direct DB queries live here; the router delegates to these functions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, desc, func, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_threat_counts_and_recent(
    sess: AsyncSession,
    org_id: Optional[str],
    is_superadmin: bool,
    cutoff: datetime,
) -> tuple[dict, list]:
    """
    Query unresolved events in the last 24 h, grouped by severity.
    Returns (counts_dict, recent_list).
    """
    from aether_os.core.guardian.models import GuardianEvent

    q_counts = (
        select(GuardianEvent.severity, func.count())
        .where(GuardianEvent.resolved == False)  # noqa: E712
        .where(GuardianEvent.created_at >= cutoff)
    )
    q_recent = (
        select(GuardianEvent)
        .where(GuardianEvent.resolved == False)  # noqa: E712
        .order_by(desc(GuardianEvent.created_at))
        .limit(5)
    )

    if not is_superadmin:
        q_counts = q_counts.where(GuardianEvent.org_id == org_id)
        q_recent = q_recent.where(GuardianEvent.org_id == org_id)

    rows = (await sess.execute(q_counts.group_by(GuardianEvent.severity))).all()
    counts = {r[0]: r[1] for r in rows}
    recent = (await sess.execute(q_recent)).scalars().all()
    return counts, list(recent)


async def get_latest_snapshot(sess: AsyncSession) -> Optional[Any]:
    """Return the most recent successful snapshot (superadmin view only)."""
    from aether_os.core.guardian.models import GuardianSnapshot

    return (await sess.execute(
        select(GuardianSnapshot)
        .where(GuardianSnapshot.status.in_(["ok", "restored"]))
        .order_by(desc(GuardianSnapshot.created_at))
        .limit(1)
    )).scalars().first()


async def get_guardian_stats(
    sess: AsyncSession,
    org_id: Optional[str],
    is_superadmin: bool,
) -> Dict[str, Any]:
    """
    Compute cumulative prevention counters for the guardian stats endpoint.
    Returns a dict matching the public API shape.
    """
    from aether_os.core.guardian.models import GuardianEvent, GuardianSnapshot

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    q_base = select(GuardianEvent).where(GuardianEvent.event_type != "recovery")
    if not is_superadmin:
        q_base = q_base.where(GuardianEvent.org_id == org_id)

    total = (await sess.execute(
        select(func.count()).select_from(q_base.subquery())
    )).scalar() or 0

    today_count = (await sess.execute(
        select(func.count()).select_from(
            q_base.where(GuardianEvent.created_at >= today).subquery()
        )
    )).scalar() or 0

    week_count = (await sess.execute(
        select(func.count()).select_from(
            q_base.where(GuardianEvent.created_at >= week_ago).subquery()
        )
    )).scalar() or 0

    q_type = select(GuardianEvent.event_type, func.count()).group_by(GuardianEvent.event_type)
    if not is_superadmin:
        q_type = q_type.where(GuardianEvent.org_id == org_id)
    by_type_rows = (await sess.execute(q_type)).all()
    by_type = {r[0]: r[1] for r in by_type_rows}

    snap_count = 0
    if is_superadmin:
        snap_count = (await sess.execute(
            select(func.count()).select_from(GuardianSnapshot)
            .where(GuardianSnapshot.status.in_(["ok", "restored"]))
        )).scalar() or 0

    q_last = (
        select(GuardianEvent.created_at)
        .where(GuardianEvent.event_type != "recovery")
        .order_by(desc(GuardianEvent.created_at))
        .limit(1)
    )
    if not is_superadmin:
        q_last = q_last.where(GuardianEvent.org_id == org_id)
    last_threat_row = (await sess.execute(q_last)).scalar()

    q_critical = (
        select(func.count()).select_from(GuardianEvent)
        .where(GuardianEvent.severity == "critical")
        .where(GuardianEvent.event_type != "recovery")
    )
    if not is_superadmin:
        q_critical = q_critical.where(GuardianEvent.org_id == org_id)
    critical_total = (await sess.execute(q_critical)).scalar() or 0

    return {
        "threats_blocked_total": total,
        "threats_blocked_today": today_count,
        "threats_blocked_week": week_count,
        "critical_incidents_total": critical_total,
        "auto_recoveries_performed": by_type.get("recovery", 0),
        "snapshots_available": snap_count,
        "by_type": by_type,
        "last_threat_at": last_threat_row.isoformat() if last_threat_row else None,
    }


async def list_events(
    sess: AsyncSession,
    org_id: Optional[str],
    is_superadmin: bool,
    limit: int,
    offset: int,
    severity: Optional[str],
    resolved: Optional[bool],
) -> tuple[int, list]:
    """
    Paginated query of guardian events with optional filters.
    Returns (total_count, rows).
    """
    from aether_os.core.guardian.models import GuardianEvent

    q = select(GuardianEvent).order_by(desc(GuardianEvent.created_at))
    if not is_superadmin:
        q = q.where(GuardianEvent.org_id == org_id)
    if severity:
        q = q.where(GuardianEvent.severity == severity)
    if resolved is not None:
        q = q.where(GuardianEvent.resolved == resolved)

    total = (await sess.execute(select(func.count()).select_from(q.subquery()))).scalar()
    rows = (await sess.execute(q.offset(offset).limit(limit))).scalars().all()
    return total, list(rows)


async def resolve_event(
    sess: AsyncSession,
    event_id: str,
    org_id: Optional[str],
    is_superadmin: bool,
) -> int:
    """
    Mark a guardian event as resolved. Returns rowcount (0 = not found).
    Caller must commit the session.
    """
    ts = datetime.now(timezone.utc)
    if not is_superadmin:
        query = text(
            "UPDATE guardian_events SET resolved = true, resolved_at = :ts "
            "WHERE id = :eid AND org_id = :oid"
        )
        params: Dict[str, Any] = {"ts": ts, "eid": event_id, "oid": org_id}
    else:
        query = text(
            "UPDATE guardian_events SET resolved = true, resolved_at = :ts "
            "WHERE id = :eid"
        )
        params = {"ts": ts, "eid": event_id}

    result = await sess.execute(query, params)
    return result.rowcount
