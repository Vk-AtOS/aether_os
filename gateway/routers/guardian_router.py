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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from aether_os.gateway.dependencies import get_current_user, security_scheme
from aether_os.core.services.guardian_service import (
    get_threat_counts_and_recent,
    get_latest_snapshot,
    get_guardian_stats,
    list_events as svc_list_events,
)

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

    try:
        from aether_os.core.db import get_session_factory

        is_superadmin = user.get("role") == "superadmin"
        org_id = user.get("org_id")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        sf = get_session_factory()
        async with sf() as sess:
            counts, recent = await get_threat_counts_and_recent(sess, org_id, is_superadmin, cutoff)
            latest_snap = await get_latest_snapshot(sess) if is_superadmin else None

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
    org_id = user.get("org_id")
    sf = get_session_factory()
    try:
        async with sf() as sess:
            return await get_guardian_stats(sess, org_id, is_superadmin)
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
    org_id = user.get("org_id")
    sf = get_session_factory()
    async with sf() as sess:
        total, rows = await svc_list_events(sess, org_id, is_superadmin, limit, offset, severity, resolved)

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
