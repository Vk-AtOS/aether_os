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
  POST /admin/system/deploy
  POST /admin/platform/save-file
"""
from __future__ import annotations
import logging
import os
import pathlib
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user
from aether_os.core.retention import prune_artifact_files
from aether_os.core.db import get_session_factory
from aether_os.core.db_utils import update_run_status
from aether_os.core.guardian.threat_detector import get_threat_detector
from aether_os.core.guardian.threat_detector import _CRITICAL_FILES
from aether_os.core.models import Run
from aether_os.core.models import Run as _Run
from aether_os.core.pipeline_state import get_redis
from aether_os.core.pipeline_state import set_control
from sqlalchemy import select
from sqlalchemy import func as sqlfunc
import shutil
import subprocess as _sp
import sys as _sys
logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"])
def _current_user():
    return Depends(get_current_user)
@router.get("/admin/platform-health")
async def platform_health(user: Dict[str, Any] = _current_user()):
    # Host-wide numbers (every org's running builds, the server's disk): platform operator only.
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Platform operator access required")
    sf = get_session_factory()
    async with sf() as session:
        active = (await session.execute(select(sqlfunc.count()).select_from(Run).where(Run.status == "running"))).scalar_one()
    disk = shutil.disk_usage("/")
    disk_pct = round(disk.used / disk.total * 100, 1)
    redis_ok = False
    try:
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
    """Delete artifact files older than `ttl_days` (default 30). Superadmin only.

    ARTIFACT_DIR is one directory for the whole platform, not per organisation,
    so an org owner/admin (which every self-registered user is, in their own org)
    must not be able to list or delete it.
    """
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin only")
    try:
        ttl_days = int(req.get("ttl_days", 30))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="ttl_days must be a whole number of days") from None
    # 0 or a negative value moves the cutoff to now or the future: every file would go.
    if ttl_days < 1:
        raise HTTPException(status_code=422, detail="ttl_days must be at least 1")
    dry_run   = bool(req.get("dry_run", False))
    artifacts_root = pathlib.Path(os.environ.get("ARTIFACT_DIR", "artifacts"))
    deleted_files, deleted_bytes = prune_artifact_files(artifacts_root, ttl_days, dry_run)
    return {
        "dry_run": dry_run,
        "ttl_days": ttl_days,
        "deleted_count": len(deleted_files),
        "deleted_bytes": deleted_bytes,
        "deleted_mb": round(deleted_bytes / 1_048_576, 2),
        "files": deleted_files[:50],
    }
@router.post("/admin/system/deploy")
async def system_deploy(user: Dict[str, Any] = _current_user()):
    """Pull latest code from git and restart the service.
    ARCH-H3: Restricted to superadmin only — any lower role would allow git remote
    compromise to become full host takeover via arbitrary code execution.
    All calls are logged at WARNING with the caller's user ID.
    """
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin access required for platform deployment")
    # ARCH-H3: always log at WARNING so every deploy attempt is visible in production logs
    logger.warning(
        "admin_system_deploy: called by user=%s (sub=%s) — initiating git pull + service restart",
        user.get("user_id", "?"), user.get("sub", "?"),
    )
    install_dir = pathlib.Path(__file__).resolve().parents[2]
    log: list[str] = []
    # 1. Stash any local changes so pull never blocks
    stash = _sp.run(
        ["git", "stash"],
        cwd=str(install_dir), capture_output=True, text=True, timeout=30,
    )
    if stash.stdout.strip():
        log.append(f"git stash: {stash.stdout.strip()}")
    # 2. git pull
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc