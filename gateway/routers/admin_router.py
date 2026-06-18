"""
AetherOS — Admin Router
GET  /admin/users
POST /admin/users/invite
POST /admin/users/{user_id}/role
POST /admin/users/{user_id}/deactivate

Platform management routes (platform-health, kill-all, prune-artifacts,
audit-logs/export, system/deploy, platform/save-file) live in
admin_platform_router.py.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

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

    # Send invite email with temp credentials
    email_sent = False
    try:
        from aether_os.core.notifications.email import get_email_notifier
        frontend_url = os.environ.get("FRONTEND_URL", "https://app.aetheros.ai").rstrip("/")
        login_url = f"{frontend_url}/login"
        inviter_name = user.get("sub", "Your organisation")
        notifier = get_email_notifier()
        body_html = (
            f"<p>You've been invited to join <strong>AetherOS</strong> by {inviter_name}.</p>"
            f"<p>Your temporary credentials:</p>"
            f"<ul><li><strong>Email:</strong> {email}</li>"
            f"<li><strong>Temporary password:</strong> <code>{temp_password}</code></li></ul>"
            f"<p><a href='{login_url}' style='background:#7c3aed;color:#fff;padding:10px 20px;"
            f"border-radius:6px;text-decoration:none;display:inline-block'>Sign in to AetherOS</a></p>"
            f"<p>Please change your password after your first login.</p>"
            f"<hr><p style='color:#888;font-size:12px'>AetherOS</p>"
        )
        body_text = (
            f"You've been invited to join AetherOS by {inviter_name}.\n\n"
            f"Your temporary credentials:\n  Email: {email}\n  Password: {temp_password}\n\n"
            f"Sign in at: {login_url}\n\nPlease change your password after your first login."
        )
        email_sent = await notifier.send(email, "You've been invited to AetherOS", body_html, body_text)
    except Exception as exc:
        logger.warning("Invite email failed for %s: %s", email, exc)

    return {
        "id": new_user.id,
        "email": email,
        "role": role,
        "email_sent": email_sent,
        # Only include temp_password when email could not be sent so admin can share it manually
        **({"temp_password": temp_password} if not email_sent else {}),
    }


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


# Platform management routes live in admin_platform_router.py —
# see gateway/routers/admin_platform_router.py
