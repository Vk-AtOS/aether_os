"""
AetherOS Guardian Router

GET  /guardian/status  — threat level, last snapshot, service health  (authenticated)
GET  /guardian/stats   — cumulative prevention counters                (authenticated)
GET  /guardian/events  — paginated threat event log                    (admin)

Snapshot management, event resolution, restore, and baseline-refresh routes
live in guardian_snapshots_router.py.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from aether_os.gateway.dependencies import get_current_user, security_scheme

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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> Dict[str, Any]:
    """Current threat level, last snapshot, and live service health."""
    
    # Try to authenticate
    user: Optional[Dict[str, Any]] = None
    if credentials:
        try:
            user = await get_current_user(credentials)
        except HTTPException as e:
            logger.warning("guardian_router: authentication failed (will return public stub): %s", e.detail)

    # Unauthenticated callers get only a safe stub — no DB query, no data leak
    if not user:
        return {"threat_level": "unknown", "recent_threats": []}

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

            # Base queries — always scoped to org unless superadmin
            q_counts = (
                select(GuardianEvent.severity, func.count())
                .where(GuardianEvent.resolved == False)
                .where(GuardianEvent.created_at >= cutoff)
            )
            q_recent = (
                select(GuardianEvent)
                .where(GuardianEvent.resolved == False)
                .order_by(desc(GuardianEvent.created_at))
                .limit(5)
            )

            if user.get("role") != "superadmin":
                org_id = user["org_id"]
                q_counts = q_counts.where(GuardianEvent.org_id == org_id)
                q_recent = q_recent.where(GuardianEvent.org_id == org_id)

            rows = (await sess.execute(q_counts.group_by(GuardianEvent.severity))).all()
            counts = {r[0]: r[1] for r in rows}

            # Latest snapshot (platform-level, only for superadmins)
            latest_snap = None
            if user.get("role") == "superadmin":
                latest_snap = (await sess.execute(
                    select(GuardianSnapshot)
                    .where(GuardianSnapshot.status.in_(["ok", "restored"]))
                    .order_by(desc(GuardianSnapshot.created_at))
                    .limit(1)
                )).scalars().first()

            # Recent unresolved events
            recent = (await sess.execute(q_recent)).scalars().all()

        # Determine threat level for authenticated users
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
async def guardian_stats(user: Dict[str, Any] = _get_current_user()) -> Dict[str, Any]:
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

            # Base event query filtered by org
            q_base = select(GuardianEvent).where(GuardianEvent.event_type != "recovery")
            if user.get("role") != "superadmin":
                q_base = q_base.where(GuardianEvent.org_id == user["org_id"])

            # Total threats
            total = (await sess.execute(
                select(func.count()).select_from(q_base.subquery())
            )).scalar() or 0

            # Today
            today_count = (await sess.execute(
                select(func.count()).select_from(q_base.where(GuardianEvent.created_at >= today).subquery())
            )).scalar() or 0

            # This week
            week_count = (await sess.execute(
                select(func.count()).select_from(q_base.where(GuardianEvent.created_at >= week_ago).subquery())
            )).scalar() or 0

            # Breakdown by type
            q_type = select(GuardianEvent.event_type, func.count()).group_by(GuardianEvent.event_type)
            if user.get("role") != "superadmin":
                q_type = q_type.where(GuardianEvent.org_id == user["org_id"])
            by_type_rows = (await sess.execute(q_type)).all()
            by_type = {r[0]: r[1] for r in by_type_rows}

            # Auto-recoveries performed
            recoveries = by_type.get("recovery", 0)

            # Snapshots available (platform-level, only for superadmins)
            snap_count = 0
            if user.get("role") == "superadmin":
                snap_count = (await sess.execute(
                    select(func.count()).select_from(GuardianSnapshot)
                    .where(GuardianSnapshot.status.in_(["ok", "restored"]))
                )).scalar() or 0

            # Last threat timestamp
            q_last = select(GuardianEvent.created_at).where(GuardianEvent.event_type != "recovery").order_by(desc(GuardianEvent.created_at)).limit(1)
            if user.get("role") != "superadmin":
                q_last = q_last.where(GuardianEvent.org_id == user["org_id"])
            last_threat_row = (await sess.execute(q_last)).scalar()

            # Critical incidents
            q_critical = select(func.count()).select_from(GuardianEvent).where(GuardianEvent.severity == "critical").where(GuardianEvent.event_type != "recovery")
            if user.get("role") != "superadmin":
                q_critical = q_critical.where(GuardianEvent.org_id == user["org_id"])
            critical_total = (await sess.execute(q_critical)).scalar() or 0

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
        
        # Filter by org_id for non-superadmins
        if user.get("role") != "superadmin":
            q = q.where(GuardianEvent.org_id == user["org_id"])
            
        if severity:
            q = q.where(GuardianEvent.severity == severity)
        if resolved is not None:
            q = q.where(GuardianEvent.resolved == resolved)
        total = (await sess.execute(select(func.count()).select_from(q.subquery()))).scalar()
        rows = (await sess.execute(q.offset(offset).limit(limit))).scalars().all()

    is_superadmin = user.get("role") == "superadmin"

    def _sanitize_detail(detail: Any) -> Any:
        """Strip full filesystem paths from detail for non-superadmin users."""
        if not detail or not isinstance(detail, dict):
            return detail
        sanitized = dict(detail)
        if "file" in sanitized and isinstance(sanitized["file"], str):
            sanitized["file"] = os.path.basename(sanitized["file"])
        return sanitized

    return {
        "total": total,
        "items": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "severity": e.severity,
                "source_ip": e.source_ip,
                "endpoint": e.endpoint,
                "detail": e.detail if is_superadmin else _sanitize_detail(e.detail),
                "resolved": e.resolved,
                "created_at": e.created_at.isoformat(),
                "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
            }
            for e in rows
        ],
    }

# Snapshot management, event resolution, restore, and baseline-refresh routes live in
# guardian_snapshots_router.py — see gateway/routers/guardian_snapshots_router.py
