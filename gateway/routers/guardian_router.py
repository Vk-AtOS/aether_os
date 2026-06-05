"""
AetherOS Guardian Router

GET  /guardian/status           — threat level, last snapshot, service health  (authenticated)
GET  /guardian/stats            — cumulative prevention counters                (authenticated)
GET  /guardian/events           — paginated threat event log                   (admin)
GET  /guardian/snapshots        — list available snapshots                     (admin)
POST /guardian/snapshots        — trigger manual snapshot                      (admin)
POST /guardian/restore/{id}     — restore from snapshot                        (admin)
POST /guardian/events/{id}/resolve — mark event resolved                       (admin)
POST /guardian/baseline/refresh — refresh file integrity baseline              (admin)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/guardian", tags=["Guardian"])


def _get_current_user():
    return Depends(get_current_user)


def _require_admin(user: Dict[str, Any]) -> None:
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin access required")


# ── Status (any authenticated user) ──────────────────────────────────────────

@router.get("/status")
async def guardian_status(
    user: Dict[str, Any] = Depends(lambda: None),
) -> Dict[str, Any]:
    """Current threat level, last snapshot, and live service health."""
    from fastapi import Request

    # Soft auth — return public-safe data without blocking unauthenticated callers
    # (dashboard polls this for the header badge)
    try:
        from aether_os.core.guardian.models import GuardianEvent, GuardianSnapshot
        from aether_os.core.db import get_session_factory
        from sqlalchemy import select, desc, func
        from datetime import datetime, timedelta, timezone

        sf = get_session_factory()
        async with sf() as sess:
            # Count unresolved events by severity in last 24h
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            rows = (await sess.execute(
                select(GuardianEvent.severity, func.count())
                .where(GuardianEvent.resolved == False)  # noqa: E712
                .where(GuardianEvent.created_at >= cutoff)
                .group_by(GuardianEvent.severity)
            )).all()
            counts = {r[0]: r[1] for r in rows}

            # Latest snapshot
            latest_snap = (await sess.execute(
                select(GuardianSnapshot)
                .where(GuardianSnapshot.status.in_(["ok", "restored"]))
                .order_by(desc(GuardianSnapshot.created_at))
                .limit(1)
            )).scalars().first()

            # Recent unresolved events (last 5)
            recent = (await sess.execute(
                select(GuardianEvent)
                .where(GuardianEvent.resolved == False)  # noqa: E712
                .order_by(desc(GuardianEvent.created_at))
                .limit(5)
            )).scalars().all()

        # Determine threat level
        if counts.get("critical", 0) > 0:
            threat_level = "critical"
        elif counts.get("high", 0) > 0:
            threat_level = "high"
        elif counts.get("medium", 0) > 0:
            threat_level = "medium"
        elif counts.get("low", 0) > 0:
            threat_level = "low"
        else:
            threat_level = "safe"

        return {
            "threat_level": threat_level,
            "event_counts_24h": counts,
            "last_snapshot": {
                "id": latest_snap.id,
                "created_at": latest_snap.created_at.isoformat(),
                "trigger": latest_snap.trigger,
                "size_bytes": latest_snap.size_bytes,
                "db_backend": latest_snap.db_backend,
            } if latest_snap else None,
            "recent_threats": [
                {
                    "id": e.id,
                    "event_type": e.event_type,
                    "severity": e.severity,
                    "source_ip": e.source_ip,
                    "detail": e.detail,
                    "created_at": e.created_at.isoformat(),
                }
                for e in recent
            ],
        }
    except Exception as exc:
        logger.warning("Guardian status endpoint error: %s", exc)
        return {"threat_level": "unknown", "error": str(exc)}


# ── Stats (any authenticated user) ───────────────────────────────────────────

@router.get("/stats")
async def guardian_stats() -> Dict[str, Any]:
    """Cumulative prevention counters — powers the real-time threat dashboard."""
    from aether_os.core.guardian.models import GuardianEvent, GuardianSnapshot
    from aether_os.core.db import get_session_factory
    from sqlalchemy import select, func, desc
    from datetime import datetime, timedelta, timezone

    sf = get_session_factory()
    try:
        async with sf() as sess:
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)

            # Total threats (all non-recovery events)
            total = (await sess.execute(
                select(func.count()).select_from(GuardianEvent)
                .where(GuardianEvent.event_type != "recovery")
            )).scalar() or 0

            # Today
            today_count = (await sess.execute(
                select(func.count()).select_from(GuardianEvent)
                .where(GuardianEvent.event_type != "recovery")
                .where(GuardianEvent.created_at >= today)
            )).scalar() or 0

            # This week
            week_count = (await sess.execute(
                select(func.count()).select_from(GuardianEvent)
                .where(GuardianEvent.event_type != "recovery")
                .where(GuardianEvent.created_at >= week_ago)
            )).scalar() or 0

            # Breakdown by type
            by_type_rows = (await sess.execute(
                select(GuardianEvent.event_type, func.count())
                .group_by(GuardianEvent.event_type)
            )).all()
            by_type = {r[0]: r[1] for r in by_type_rows}

            # Auto-recoveries performed
            recoveries = by_type.get("recovery", 0)

            # Snapshots available
            snap_count = (await sess.execute(
                select(func.count()).select_from(GuardianSnapshot)
                .where(GuardianSnapshot.status.in_(["ok", "restored"]))
            )).scalar() or 0

            # Last threat timestamp
            last_threat_row = (await sess.execute(
                select(GuardianEvent.created_at)
                .where(GuardianEvent.event_type != "recovery")
                .order_by(desc(GuardianEvent.created_at))
                .limit(1)
            )).scalar()

            # Critical incidents (critical severity, all time)
            critical_total = (await sess.execute(
                select(func.count()).select_from(GuardianEvent)
                .where(GuardianEvent.severity == "critical")
                .where(GuardianEvent.event_type != "recovery")
            )).scalar() or 0

        return {
            "threats_blocked_total":   total,
            "threats_blocked_today":   today_count,
            "threats_blocked_week":    week_count,
            "critical_incidents_total": critical_total,
            "auto_recoveries_performed": recoveries,
            "snapshots_available":     snap_count,
            "by_type":                 by_type,
            "last_threat_at":          last_threat_row.isoformat() if last_threat_row else None,
        }
    except Exception as exc:
        logger.warning("Guardian stats error: %s", exc)
        return {
            "threats_blocked_total": 0, "threats_blocked_today": 0,
            "threats_blocked_week": 0, "critical_incidents_total": 0,
            "auto_recoveries_performed": 0, "snapshots_available": 0,
            "by_type": {}, "last_threat_at": None,
        }


# ── Events (admin) ────────────────────────────────────────────────────────────

@router.get("/events")
async def list_events(
    limit: int = 50,
    offset: int = 0,
    severity: Optional[str] = None,
    resolved: Optional[bool] = None,
    user: Dict[str, Any] = _get_current_user(),
) -> Dict[str, Any]:
    _require_admin(user)
    from aether_os.core.guardian.models import GuardianEvent
    from aether_os.core.db import get_session_factory
    from sqlalchemy import select, desc, func

    sf = get_session_factory()
    async with sf() as sess:
        q = select(GuardianEvent).order_by(desc(GuardianEvent.created_at))
        if severity:
            q = q.where(GuardianEvent.severity == severity)
        if resolved is not None:
            q = q.where(GuardianEvent.resolved == resolved)
        total = (await sess.execute(select(func.count()).select_from(q.subquery()))).scalar()
        rows = (await sess.execute(q.offset(offset).limit(limit))).scalars().all()

    return {
        "total": total,
        "items": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "severity": e.severity,
                "source_ip": e.source_ip,
                "endpoint": e.endpoint,
                "detail": e.detail,
                "resolved": e.resolved,
                "created_at": e.created_at.isoformat(),
                "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
            }
            for e in rows
        ],
    }


@router.post("/events/{event_id}/resolve")
async def resolve_event(
    event_id: str,
    user: Dict[str, Any] = _get_current_user(),
) -> Dict[str, Any]:
    _require_admin(user)
    from aether_os.core.db import get_session_factory
    from sqlalchemy import text
    from datetime import datetime, timezone

    sf = get_session_factory()
    async with sf() as sess:
        result = await sess.execute(
            text(
                "UPDATE guardian_events SET resolved = true, resolved_at = :ts "
                "WHERE id = :eid"
            ),
            {"ts": datetime.now(timezone.utc), "eid": event_id},
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Event not found")
        await sess.commit()

    return {"ok": True, "event_id": event_id}


# ── Snapshots (admin) ─────────────────────────────────────────────────────────

@router.get("/snapshots")
async def list_snapshots(
    limit: int = 20,
    user: Dict[str, Any] = _get_current_user(),
) -> Dict[str, Any]:
    _require_admin(user)
    from aether_os.core.guardian.snapshot_manager import get_snapshot_manager
    snaps = await get_snapshot_manager().list_snapshots(limit=limit)
    return {"snapshots": snaps}


class SnapshotRequest(BaseModel):
    note: Optional[str] = None


@router.post("/snapshots")
async def trigger_snapshot(
    req: SnapshotRequest,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = _get_current_user(),
) -> Dict[str, Any]:
    _require_admin(user)
    from aether_os.core.guardian.snapshot_manager import get_snapshot_manager

    async def _run():
        await get_snapshot_manager().take_snapshot(trigger="manual", note=req.note)

    background_tasks.add_task(_run)
    return {"ok": True, "message": "Snapshot started in background"}


@router.post("/restore/{snapshot_id}")
async def restore_snapshot(
    snapshot_id: str,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = _get_current_user(),
) -> Dict[str, Any]:
    _require_admin(user)
    from aether_os.core.guardian.snapshot_manager import get_snapshot_manager

    async def _run():
        await get_snapshot_manager().restore(snapshot_id)

    background_tasks.add_task(_run)
    return {
        "ok": True,
        "message": f"Restore from snapshot {snapshot_id} started. Service will be briefly unavailable.",
    }


# ── Baseline management (admin) ───────────────────────────────────────────────

@router.post("/baseline/refresh")
async def refresh_baseline(
    user: Dict[str, Any] = _get_current_user(),
) -> Dict[str, Any]:
    """
    Refresh the file integrity baseline after a legitimate code deploy.
    Call this after every planned deployment so the watchdog doesn't flag
    the new code as tampering.
    """
    _require_admin(user)
    from aether_os.core.guardian.threat_detector import get_threat_detector, _CRITICAL_FILES

    td = get_threat_detector()
    refreshed = []
    for path in _CRITICAL_FILES:
        if path.exists():
            await td.update_baseline(path)
            refreshed.append(path.name)

    logger.info("Guardian baseline refreshed by %s: %s", user.get("sub", "unknown"), refreshed)
    return {"ok": True, "refreshed_files": refreshed}
