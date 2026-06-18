"""
AetherOS — Admin Platform Router
=================================
Platform management routes (health, kill-all, prune-artifacts, audit-logs,
system deploy, save-file).  User management routes live in admin_router.py.

Routes
------
  GET  /admin/platform-health
  POST /admin/kill-all
  POST /admin/prune-artifacts
  GET  /admin/audit-logs/export
  POST /admin/system/deploy
  POST /admin/platform/save-file
"""
from __future__ import annotations

import csv
import io
import logging
import os
import pathlib
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"])


def _current_user():
    return Depends(get_current_user)


@router.get("/admin/platform-health")
async def platform_health(user: Dict[str, Any] = _current_user()):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    import shutil
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select, func as sqlfunc

    sf = get_session_factory()
    async with sf() as session:
        active = (await session.execute(select(sqlfunc.count()).select_from(Run).where(Run.status == "running"))).scalar_one()

    disk = shutil.disk_usage("/")
    disk_pct = round(disk.used / disk.total * 100, 1)

    redis_ok = False
    try:
        from aether_os.core.pipeline_state import get_redis
        r = await get_redis()
        if r:
            await r.ping()
            redis_ok = True
    except Exception as exc:
        logger.debug("platform_health: redis ping failed: %s", exc)

    return {
        "redis_connected": redis_ok,
        "active_pipelines": active,
        "disk_usage_pct": disk_pct,
        "disk_free_gb": round(disk.free / 1e9, 1),
    }


@router.post("/admin/kill-all")
async def kill_all(user: Dict[str, Any] = _current_user()):
    if user.get("role") != "owner":
        raise HTTPException(status_code=403)
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run as _Run
    from aether_os.core.pipeline_state import set_control
    from aether_os.core.db_utils import update_run_status
    from sqlalchemy import select
    sf = get_session_factory()
    async with sf() as _sess:
        run_ids = (await _sess.execute(
            select(_Run.id).where(_Run.org_id == user["org_id"], _Run.status == "running")
        )).scalars().all()
    for rid in run_ids:
        await set_control(rid, "cancel")
        await update_run_status(rid, "cancelled", org_id=user["org_id"])
    return {"killed_count": len(run_ids)}


@router.post("/admin/prune-artifacts")
async def prune_artifacts(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """Delete artifact files older than `ttl_days` (default 30). Admin only."""
    import shutil
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    ttl_days = int(req.get("ttl_days", 30))
    dry_run   = bool(req.get("dry_run", False))
    artifacts_root = pathlib.Path(os.environ.get("ARTIFACT_DIR", "artifacts"))
    cutoff = time.time() - ttl_days * 86400
    deleted_files: list[str] = []
    deleted_bytes = 0
    if artifacts_root.exists():
        for p in sorted(artifacts_root.rglob("*")):
            if p.is_file() and p.stat().st_mtime < cutoff:
                deleted_bytes += p.stat().st_size
                deleted_files.append(str(p.relative_to(artifacts_root)))
                if not dry_run:
                    p.unlink(missing_ok=True)
        # Remove empty dirs
        if not dry_run:
            for p in sorted(artifacts_root.rglob("*"), reverse=True):
                if p.is_dir():
                    try:
                        p.rmdir()
                    except OSError as e:
                        logger.warning("admin_platform_router: could not remove empty dir %s: %s", p, e)
    return {
        "dry_run": dry_run,
        "ttl_days": ttl_days,
        "deleted_count": len(deleted_files),
        "deleted_bytes": deleted_bytes,
        "deleted_mb": round(deleted_bytes / 1_048_576, 2),
        "files": deleted_files[:50],
    }


@router.get("/admin/audit-logs/export")
async def export_audit_logs(
    from_date: Optional[str] = Query(None, description="Start date ISO-8601 (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="End date ISO-8601 (YYYY-MM-DD)"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    action: Optional[str] = Query(None, description="Filter by action string (partial match)"),
    user: Dict[str, Any] = _current_user(),
):
    """Export audit logs as a CSV file. Admin/owner only."""
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    from aether_os.core.db import get_session_factory
    from aether_os.core.models import AuditLog, User as UserModel
    from sqlalchemy import select, and_

    sf = get_session_factory()

    # Parse date bounds into Unix timestamps (AuditLog.created_at is a Float epoch)
    ts_from: Optional[float] = None
    ts_to: Optional[float] = None
    try:
        if from_date:
            ts_from = datetime.strptime(from_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            ).timestamp()
        if to_date:
            # Include the full "to" day by advancing to start of next day
            dt_to = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            ts_to = (
                dt_to.replace(hour=23, minute=59, second=59, microsecond=999999)
            ).timestamp()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}")

    org_id = user["org_id"]

    async with sf() as session:
        stmt = select(AuditLog, UserModel.email).outerjoin(
            UserModel, UserModel.id == AuditLog.user_id
        ).where(AuditLog.org_id == org_id)

        if ts_from is not None:
            stmt = stmt.where(AuditLog.created_at >= ts_from)
        if ts_to is not None:
            stmt = stmt.where(AuditLog.created_at <= ts_to)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action:
            stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))

        stmt = stmt.order_by(AuditLog.created_at.asc())
        rows = (await session.execute(stmt)).all()

    def _generate_csv():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "timestamp", "user_email", "user_id", "action",
            "resource_type", "resource_id", "ip_address", "org_id",
        ])
        buf.seek(0)
        yield buf.read()

        for log, email in rows:
            buf = io.StringIO()
            writer = csv.writer(buf)
            ts_str = datetime.fromtimestamp(log.created_at, tz=timezone.utc).isoformat() if log.created_at else ""
            writer.writerow([
                ts_str,
                email or "",
                log.user_id,
                log.action,
                log.resource_type,
                log.resource_id,
                log.ip_address or "",
                log.org_id,
            ])
            buf.seek(0)
            yield buf.read()

    # Build a descriptive filename
    date_part = f"{from_date or 'all'}_{to_date or 'now'}"
    filename = f"audit-logs_{date_part}.csv"

    return StreamingResponse(
        _generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/system/deploy")
async def system_deploy(user: Dict[str, Any] = _current_user()):
    """Pull latest code from git and restart the service. Owner/admin only."""
    import subprocess as _sp
    import sys as _sys
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Owner or admin required")

    install_dir = pathlib.Path(__file__).resolve().parents[2]
    log: list[str] = []

    # 1. git pull
    pull = _sp.run(
        ["git", "pull", "--ff-only"],
        cwd=str(install_dir), capture_output=True, text=True, timeout=60,
    )
    log.append(f"git pull: rc={pull.returncode}")
    if pull.stdout.strip():
        log.append(pull.stdout.strip())
    if pull.stderr.strip():
        log.append(pull.stderr.strip())

    # 2. pip install in case dependencies changed
    venv_pip = install_dir / "venv" / "bin" / "pip"
    pip_bin = str(venv_pip) if venv_pip.exists() else _sys.executable.replace("python", "pip").replace("python3", "pip3")
    _sp.run(
        [pip_bin, "install", "-q", "-e", str(install_dir)],
        capture_output=True, timeout=120,
    )

    # 3. Refresh Guardian baseline (P9 fix: MUST happen before restart)
    try:
        from aether_os.core.guardian.threat_detector import get_threat_detector
        td = get_threat_detector()
        await td.update_all_baselines()
        log.append("Guardian baseline updated")
    except Exception as exc:
        logger.error("Failed to update Guardian baseline: %s", exc)
        log.append(f"Guardian baseline update failed: {exc}")

    # 4. Restart systemd service (non-blocking — response sent before process dies)
    restart = _sp.Popen(
        ["systemctl", "restart", "aetheros"],
        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
    )
    log.append(f"systemctl restart: pid={restart.pid}")

    return {"ok": pull.returncode == 0, "log": log}


class PlatformFileWrite(BaseModel):
    file_path: str
    content: str


@router.post("/admin/platform/save-file")
async def save_platform_file(
    req: PlatformFileWrite,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Apply a code fix to a platform-level monitored file (P9)."""
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin access required")

    from aether_os.core.guardian.threat_detector import get_threat_detector, _CRITICAL_FILES
    from pathlib import Path

    # Security check: only allow monitored files
    target = next((f for f in _CRITICAL_FILES if f.name == req.file_path or str(f).endswith(req.file_path)), None)
    if not target:
        raise HTTPException(status_code=403, detail="File is not monitored or not allowed for direct edit")

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        # 1. Write the new content
        target.write_text(req.content, encoding="utf-8")

        # 2. Update baseline atomically (P9)
        td = get_threat_detector()
        await td.update_baseline(target)

        logger.info("Admin applied fix to %s and updated Guardian baseline", target.name)
        return {"ok": True, "file": target.name, "baseline_updated": True}
    except Exception as exc:
        logger.error("Failed to save platform fix to %s: %s", target.name, exc)
        raise HTTPException(status_code=500, detail=str(exc))
