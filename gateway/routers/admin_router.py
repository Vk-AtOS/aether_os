"""
AetherOS — Admin Router
GET  /admin/users
POST /admin/users/invite
POST /admin/users/{user_id}/role
POST /admin/users/{user_id}/deactivate
POST /admin/users/{user_id}/reactivate
POST /admin/users/{user_id}/reset-password
GET  /admin/audit/export.csv
GET  /admin/error-registry
GET  /admin/error-registry/summary
POST /admin/error-registry/{category}/mark-fixed

Platform management routes (platform-health, kill-all, prune-artifacts,
audit-logs/export, system/deploy, platform/save-file) live in
admin_platform_router.py.
Quality metrics routes (quality-metrics, run-costs, phase-latency) live in
admin_quality_router.py.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.services.admin_service import (
    invite_user_service,
    reset_user_password_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"])

# Error registry — imported at module level with graceful fallback
try:
    from aether_os.core.error_registry import get_registry, ErrorCategory
    _registry_available = True
except ImportError:
    _registry_available = False
    logger.warning("admin_router: core.error_registry not available — error-registry endpoints will return 503")


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

    # M10/L3: Organisation import removed (was unused); logic moved to admin_service
    return await invite_user_service(
        email=email,
        role=role,
        org_id=user["org_id"],
        inviter_name=user.get("sub", "Your organisation"),
    )


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


@router.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, user: Dict[str, Any] = _current_user()):
    """Reset a user's password to a temporary value.  Admin/owner only.

    SEC-H1: temp_password is only included in the response when the email could NOT
    be sent — so the admin can share it manually.
    FIX-15: must_change_password is set to True so the dependency layer enforces a
    password change before the user can call any other endpoint.
    """
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return await reset_user_password_service(
        user_id=user_id,
        org_id=user["org_id"],
        admin_sub=user.get("sub", "?"),
    )


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


@router.post("/admin/users/{user_id}/reactivate")
async def reactivate_user(
    user_id: str,
    user: Dict[str, Any] = _current_user(),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from sqlalchemy import select

    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        target = (await session.execute(
            select(User).where(User.id == user_id, User.org_id == org_id)
        )).scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        target.is_active = True
        await session.commit()
    return {"success": True, "user_id": user_id}


@router.get("/admin/audit/export.csv")
async def export_audit_csv(
    from_date: Optional[str] = Query(None, description="Start date ISO-8601 (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="End date ISO-8601 (YYYY-MM-DD)"),
    org_id: Optional[str] = Query(None, description="Filter by org (superadmin only)"),
    action: Optional[str] = Query(None, description="Filter by action type (partial match)"),
    user: Dict[str, Any] = _current_user(),
):
    """
    Export AuditLog rows as a streaming CSV download. Admin/owner only.
    Superadmins may pass org_id to export logs for a specific organisation;
    all other roles are scoped to their own org_id.
    """
    if user.get("role") not in ("owner", "admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Superadmin can override org_id; all others are locked to their own org.
    is_superadmin = user.get("role") == "superadmin"
    effective_org_id: Optional[str] = org_id if (is_superadmin and org_id) else user["org_id"]

    # Parse date bounds → Unix timestamps (AuditLog.created_at is a Float epoch)
    ts_from: Optional[float] = None
    ts_to: Optional[float] = None
    try:
        if from_date:
            ts_from = datetime.strptime(from_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            ).timestamp()
        if to_date:
            # Include the full to_date day by advancing to end of that day.
            dt_to = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            ts_to = dt_to.replace(
                hour=23, minute=59, second=59, microsecond=999999
            ).timestamp()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}")

    from aether_os.core.db import get_session_factory
    from aether_os.core.models import AuditLog, User as UserModel
    from sqlalchemy import select

    sf = get_session_factory()
    async with sf() as session:
        stmt = (
            select(AuditLog, UserModel.email)
            .outerjoin(UserModel, UserModel.id == AuditLog.user_id)
            .where(AuditLog.org_id == effective_org_id)
        )
        if ts_from is not None:
            stmt = stmt.where(AuditLog.created_at >= ts_from)
        if ts_to is not None:
            stmt = stmt.where(AuditLog.created_at <= ts_to)
        if action:
            stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
        stmt = stmt.order_by(AuditLog.created_at.asc())
        rows = (await session.execute(stmt)).all()

    def _generate():
        # Header row
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "timestamp", "org_id", "user_id", "user_email", "action",
            "resource_type", "resource_id", "ip_address", "log_metadata",
        ])
        buf.seek(0)
        yield buf.read()

        for log, email in rows:
            ts_str = (
                datetime.fromtimestamp(log.created_at, tz=timezone.utc).isoformat()
                if log.created_at
                else ""
            )
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                ts_str,
                log.org_id,
                log.user_id,
                email or "",
                log.action,
                log.resource_type,
                log.resource_id,
                log.ip_address or "",
                log.log_metadata or "",
            ])
            buf.seek(0)
            yield buf.read()

    date_part = f"{from_date or 'all'}_{to_date or 'now'}"
    filename = f"audit_log_{date_part}.csv"

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Platform management routes live in admin_platform_router.py —
# see gateway/routers/admin_platform_router.py
# Quality metrics routes live in admin_quality_router.py.


def _require_registry():
    """Raise 503 when the error registry module is not available."""
    if not _registry_available:
        raise HTTPException(status_code=503, detail="Error registry not available")


@router.get("/admin/error-registry")
async def list_error_registry(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return all entries from the error registry. Admin/owner only."""
    if user.get("role") not in ("owner", "admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    _require_registry()
    try:
        registry = get_registry()
        entries = registry._load()
        return {"entries": entries, "total": len(entries)}
    except Exception as exc:
        logger.warning("admin: error-registry list failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load error registry")


@router.get("/admin/error-registry/summary")
async def error_registry_summary(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return per-category counts, last-seen dates, and fix status. Admin/owner only."""
    if user.get("role") not in ("owner", "admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    _require_registry()
    try:
        registry = get_registry()
        return registry.get_summary()
    except Exception as exc:
        logger.warning("admin: error-registry summary failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to summarize error registry")


@router.post("/admin/error-registry/{category}/mark-fixed")
async def mark_error_fixed(
    category: str,
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Record a fix for a given error category. Superadmin only."""
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin access required")
    _require_registry()
    fix_description = req.get("fix_description", "").strip()
    if not fix_description:
        raise HTTPException(status_code=422, detail="fix_description is required")
    # Resolve category string to enum — fall back to UNKNOWN for unrecognised values
    try:
        cat_enum = ErrorCategory(category)
    except ValueError:
        cat_enum = ErrorCategory.UNKNOWN
        logger.warning("admin: unknown error category %r — recording as UNKNOWN", category)
    try:
        registry = get_registry()
        registry.mark_fixed(cat_enum, fix_description)
        return {"ok": True, "category": category, "fix_description": fix_description}
    except Exception as exc:
        logger.warning("admin: mark-fixed failed for category %r: %s", category, exc)
        raise HTTPException(status_code=500, detail="Failed to record fix")
