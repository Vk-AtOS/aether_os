"""
AetherOS — Admin Router
GET /admin/users
POST /admin/users/invite
POST /admin/users/{user_id}/role
POST /admin/users/{user_id}/deactivate
GET /admin/platform-health
POST /admin/kill-all
POST /admin/prune-artifacts
GET /admin/audit-logs/export
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

from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"])


def _current_user():
    return Depends(get_current_user)


@router.get("/admin/users")
async def list_users(
    user: Dict[str, Any] = _current_user(),
    page: int = 1,
    limit: int = 50,
    search: Optional[str] = None,
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from sqlalchemy import select, func
    limit = min(max(limit, 1), 100)
    page = max(page, 1)
    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        stmt = select(User).where(User.org_id == org_id)
        if search:
            stmt = stmt.where(User.email.ilike(f"%{search}%"))
        total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await session.execute(
            stmt.offset((page - 1) * limit).limit(limit)
        )).scalars().all()
    return {
        "items": [
            {"id": u.id, "email": u.email, "role": u.role,
             "is_active": u.is_active, "created_at": str(u.created_at), "last_active": None}
            for u in rows
        ],
        "page": page, "limit": limit, "total": total,
    }


@router.post("/admin/users/invite")
async def invite_user(req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    email = req.get("email", "").strip().lower()
    role = req.get("role", "member")
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="Valid email required")
    if role not in ("owner", "admin", "member", "viewer"):
        raise HTTPException(status_code=422, detail="Invalid role")
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User, Organisation
    from aether_os.gateway.auth import get_password_hash
    from sqlalchemy import select as _sel_inv
    import secrets as _sec
    sf = get_session_factory()
    async with sf() as session:
        existing = (await session.execute(
            _sel_inv(User).where(User.email == email)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="User with this email already exists")
        temp_password = _sec.token_urlsafe(16)
        new_user = User(
            org_id=user["org_id"],
            email=email,
            password_hash=get_password_hash(temp_password),
            role=role,
            is_active=True,
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
    return {"id": new_user.id, "email": email, "role": role, "temp_password": temp_password}


@router.post("/admin/users/{user_id}/role")
async def update_user_role(
    user_id: str, req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    if user.get("role") != "owner":
        raise HTTPException(status_code=403)
    new_role = req.get("role")
    if new_role not in ("owner", "admin", "member", "viewer"):
        raise HTTPException(status_code=422, detail="Invalid role")
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    sf = get_session_factory()
    async with sf() as session:
        db_user = await session.get(User, user_id)
        if not db_user or db_user.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="User not found")
        db_user.role = new_role
        await session.commit()
    return {"id": user_id, "role": new_role}


@router.post("/admin/users/{user_id}/deactivate")
async def deactivate_user(user_id: str, user: Dict[str, Any] = _current_user()):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    sf = get_session_factory()
    async with sf() as session:
        db_user = await session.get(User, user_id)
        if not db_user or db_user.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="User not found")
        db_user.is_active = False
        await session.commit()
    return {"id": user_id, "is_active": False}


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
    except Exception:
        pass

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
                    except OSError:
                        pass
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

    # 3. Restart systemd service (non-blocking — response sent before process dies)
    restart = _sp.Popen(
        ["systemctl", "restart", "aetheros"],
        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
    )
    log.append(f"systemctl restart: pid={restart.pid}")

    return {"ok": pull.returncode == 0, "log": log}
