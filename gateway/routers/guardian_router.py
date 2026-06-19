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
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.security import HTTPAuthorizationCredentials
from aether_os.gateway.dependencies import get_current_user, security_scheme
from aether_os.core.services import guardian_service
from pydantic import BaseModel

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
        except HTTPException:
            pass

    # Unauthenticated callers get only a safe stub — no DB query, no data leak
    if not user:
        return {"threat_level": "unknown", "recent_threats": []}

    # Soft auth — return public-safe data without blocking unauthenticated callers
    # (dashboard polls this for the header badge)
    try:
        from aether_os.core.db import get_session_factory
        from datetime import datetime, timedelta, timezone

        is_superadmin = user.get("role") == "superadmin"
        org_id = user.get("org_id") if not is_superadmin else None
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        sf = get_session_factory()
        async with sf() as sess:
            counts, recent = await guardian_service.get_threat_counts_and_recent(
                sess, org_id, is_superadmin, cutoff
            )
            latest_snap = None
            if is_superadmin:
                latest_snap = await guardian_service.get_latest_snapshot(sess)

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
    from aether_os.core.db import get_session_factory

    is_superadmin = user.get("role") == "superadmin"
    org_id = user.get("org_id") if not is_superadmin else None
    sf = get_session_factory()
    try:
        async with sf() as sess:
            return await guardian_service.get_guardian_stats(sess, org_id, is_superadmin)
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
    from aether_os.core.db import get_session_factory

    is_superadmin = user.get("role") == "superadmin"
    org_id = user.get("org_id") if not is_superadmin else None
    sf = get_session_factory()
    async with sf() as sess:
        total, rows = await guardian_service.list_events(
            sess, org_id, is_superadmin, limit, offset, severity, resolved
        )

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


@router.post("/events/{event_id}/resolve")
async def resolve_event(
    event_id: str,
    user: Dict[str, Any] = _get_current_user(),
) -> Dict[str, Any]:
    _require_admin(user)
    from aether_os.core.db import get_session_factory

    is_superadmin = user.get("role") == "superadmin"
    org_id = user.get("org_id") if not is_superadmin else None
    sf = get_session_factory()
    async with sf() as sess:
        rowcount = await guardian_service.resolve_event(sess, event_id, org_id, is_superadmin)
        if rowcount == 0:
            raise HTTPException(status_code=404, detail="Event not found")
        await sess.commit()

    return {"ok": True, "event_id": event_id}


# ── Snapshots (admin) ─────────────────────────────────────────────────────────

@router.get("/snapshots")
async def list_snapshots(
    limit: int = 20,
    user: Dict[str, Any] = _get_current_user(),
) -> Dict[str, Any]:
    """List available database snapshots. Platform-level, so restricted to superadmins."""
    if user.get("role") != "superadmin":
         raise HTTPException(status_code=403, detail="Superadmin access required for snapshot management")
    
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
    """Trigger a manual database snapshot. Superadmin only."""
    if user.get("role") != "superadmin":
         raise HTTPException(status_code=403, detail="Superadmin access required for snapshot management")
         
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
    """Restore the platform database from a snapshot. Superadmin only."""
    if user.get("role") != "superadmin":
         raise HTTPException(status_code=403, detail="Superadmin access required for snapshot management")

    from aether_os.core.guardian.snapshot_manager import get_snapshot_manager

    async def _run():
        await get_snapshot_manager().restore(snapshot_id)

    background_tasks.add_task(_run)
    return {
        "ok": True,
        "message": f"Restore from snapshot {snapshot_id} started. Service will be briefly unavailable.",
    }


# ── Baseline management (superadmin) ──────────────────────────────────────────

@router.post("/update-baseline")
async def update_baseline(
    req: Dict[str, Any],
    user: Dict[str, Any] = _get_current_user(),
) -> Dict[str, Any]:
    """
    Refresh the file integrity baseline for specific files.
    Superadmin only.
    """
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin access required")
        
    from aether_os.core.guardian.threat_detector import get_threat_detector, _CRITICAL_FILES
    from pathlib import Path

    file_path = req.get("file_path")
    td = get_threat_detector()
    refreshed = []
    
    if file_path:
        # Find matching file in _CRITICAL_FILES
        target = next((f for f in _CRITICAL_FILES if f.name == file_path or str(f).endswith(file_path)), None)
        if target and target.exists():
            await td.update_baseline(target)
            refreshed.append(target.name)
        else:
            raise HTTPException(status_code=404, detail="File not monitored or not found")
    else:
        # Refresh all
        for path in _CRITICAL_FILES:
            if path.exists():
                await td.update_baseline(path)
                refreshed.append(path.name)

    logger.info("Guardian baseline updated by %s: %s", user.get("sub", "unknown"), refreshed)
    return {"ok": True, "updated_files": refreshed}
