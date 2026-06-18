"""
AetherOS — Guardian Snapshots Router
=====================================
Snapshot management, restore, event resolution, and baseline refresh.
Status, stats, and event listing routes live in guardian_router.py.

Routes
------
  POST /guardian/events/{id}/resolve  — mark event resolved       (admin)
  GET  /guardian/snapshots            — list available snapshots  (superadmin)
  POST /guardian/snapshots            — trigger manual snapshot   (superadmin)
  POST /guardian/restore/{id}         — restore from snapshot     (superadmin)
  POST /guardian/update-baseline      — refresh file integrity    (superadmin)
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


# ── Event resolution (admin) ──────────────────────────────────────────────────

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
        # Check org ownership unless superadmin
        if user.get("role") != "superadmin":
            query = text(
                "UPDATE guardian_events SET resolved = true, resolved_at = :ts "
                "WHERE id = :eid AND org_id = :oid"
            )
            params = {"ts": datetime.now(timezone.utc), "eid": event_id, "oid": user["org_id"]}
        else:
            query = text(
                "UPDATE guardian_events SET resolved = true, resolved_at = :ts "
                "WHERE id = :eid"
            )
            params = {"ts": datetime.now(timezone.utc), "eid": event_id}

        result = await sess.execute(query, params)
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Event not found")
        await sess.commit()

    return {"ok": True, "event_id": event_id}


# ── Snapshots (superadmin) ────────────────────────────────────────────────────

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
