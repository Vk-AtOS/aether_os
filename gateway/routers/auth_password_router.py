"""
AetherOS — Auth Password & Email Router
Extracted from auth_router.py.

Routes for email verification and password management:
  GET  /auth/verify-email
  POST /auth/password-reset-request
  POST /auth/password-reset-confirm
  POST /auth/change-password
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


# ── Pydantic models ────────────────────────────────────────────────────────────

class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


def _auth():
    return Depends(get_current_user)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/verify-email")
async def verify_email(token: str, request: Request) -> Dict[str, str]:
    """Verify user's email address using the token."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User

    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    user_agent = request.headers.get("User-Agent", "-")
    from aether_os.core.audit.ledger import get_ledger

    try:
        from aether_os.core.pipeline_state import get_redis
        r = await get_redis()
        if not r:
            raise HTTPException(status_code=500, detail="Redis unavailable")
        user_id = await r.get(f"email_verify:{token}")
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid or expired verification token")

        # Delete token after use
        await r.delete(f"email_verify:{token}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Email verify token validation failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal error during token validation")

    sf = get_session_factory()
    async with sf() as session:
        user = await session.get(User, user_id.decode() if isinstance(user_id, bytes) else user_id)
        if not user:
            raise HTTPException(status_code=400, detail="User no longer exists")

        user.email_verified = True
        await session.commit()

        # Audit: email_verified
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=user.org_id,
            user_id=user.id,
            action="email_verified",
            ip_address=client_ip,
            user_agent=user_agent
        ))

    return {"message": "Email verified successfully. You can now log in."}


@router.post("/password-reset-request")
async def password_reset_request(req: PasswordResetRequest, request: Request) -> Dict[str, str]:
    """Request a password reset email."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from sqlalchemy import select
    import secrets

    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    user_agent = request.headers.get("User-Agent", "-")
    from aether_os.core.audit.ledger import get_ledger

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(User).where(User.email == req.email)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            token = secrets.token_urlsafe(32)
            try:
                from aether_os.core.pipeline_state import get_redis
                r = await get_redis()
                if r:
                    # Store token in Redis with 1 hour expiry
                    await r.setex(f"pw_reset:{token}", 3600, user.id)
            except Exception as exc:
                logger.debug("Failed to store password reset token in Redis for user %s: %s", user.id, exc)

            # Audit: password_reset_request
            asyncio.create_task(get_ledger().async_log_audit_event(
                org_id=user.org_id,
                user_id=user.id,
                action="password_reset_request",
                ip_address=client_ip,
                user_agent=user_agent
            ))

            # Send email
            from aether_os.core.notifications.email import get_email_notifier
            notifier = get_email_notifier()
            frontend_url = os.environ.get("FRONTEND_URL", "").rstrip("/")
            if not frontend_url:
                # Derive from the request host when FRONTEND_URL is not set
                scheme = request.headers.get("x-forwarded-proto", "https")
                host = request.headers.get("x-forwarded-host", "") or request.headers.get("host", "")
                frontend_url = f"{scheme}://{host}" if host else "https://app.aetheros.ai"
            reset_link = f"{frontend_url}/reset-password?token={token}"
            subject = "AetherOS: Password Reset Request"
            body_html = (
                f"<p>You requested a password reset for your AetherOS account.</p>"
                f"<p><a href='{reset_link}' style='background:#7c3aed;color:#fff;padding:10px 20px;"
                f"border-radius:6px;text-decoration:none;display:inline-block'>Reset Password</a></p>"
                f"<p>Or copy this link: <code>{reset_link}</code></p>"
                f"<p>This link expires in 1 hour. If you did not request this, ignore this email.</p>"
                f"<hr><p style='color:#888;font-size:12px'>AetherOS</p>"
            )
            body_text = f"Click here to reset your password: {reset_link}\n\nThis link expires in 1 hour.\n\nIf you did not request this, ignore this email."
            await notifier.send(user.email, subject, body_html, body_text)

    # Always return success to prevent email enumeration
    return {"message": "If an account exists for that email, a reset link has been sent."}


@router.post("/password-reset-confirm")
async def password_reset_confirm(req: PasswordResetConfirm, request: Request) -> Dict[str, str]:
    """Confirm password reset using the token."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from aether_os.gateway.auth import get_password_hash

    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    user_agent = request.headers.get("User-Agent", "-")
    from aether_os.core.audit.ledger import get_ledger

    try:
        from aether_os.core.pipeline_state import get_redis
        r = await get_redis()
        if not r:
            raise HTTPException(status_code=500, detail="Redis unavailable")
        user_id = await r.get(f"pw_reset:{req.token}")
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")

        # Delete token after use
        await r.delete(f"pw_reset:{req.token}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Password reset token validation failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal error during token validation")

    # Password safety: complexity + HIBP breach check
    try:
        from aether_os.core.guardian.password_shield import check_password_safety
        _pw_safe, _pw_reason = await check_password_safety(req.new_password)
        if not _pw_safe:
            raise HTTPException(status_code=422, detail=_pw_reason)
    except HTTPException:
        raise
    except Exception as _pw_exc:
        logger.warning("Password shield check failed: %s", _pw_exc)

    sf = get_session_factory()
    async with sf() as session:
        user = await session.get(User, user_id.decode() if isinstance(user_id, bytes) else user_id)
        if not user:
            raise HTTPException(status_code=400, detail="User no longer exists")

        loop = asyncio.get_running_loop()
        user.password_hash = await loop.run_in_executor(None, get_password_hash, req.new_password)
        await session.commit()

        # Audit: password_reset_confirm
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=user.org_id,
            user_id=user.id,
            action="password_reset_confirm",
            ip_address=client_ip,
            user_agent=user_agent
        ))

    return {"message": "Password has been reset successfully."}


@router.post("/change-password")
async def change_password(req: Dict[str, Any], request: Request, user: Dict[str, Any] = _auth()) -> Dict[str, str]:
    """Change the authenticated user's password with HIBP breach check."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from aether_os.gateway.auth import verify_password, get_password_hash

    user_id = user.get("user_id", "")
    current_pw = req.get("current_password", "")
    new_pw = req.get("new_password", "")

    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    user_agent = request.headers.get("User-Agent", "-")
    from aether_os.core.audit.ledger import get_ledger

    # Password safety: complexity + HIBP breach check
    try:
        from aether_os.core.guardian.password_shield import check_password_safety
        _pw_safe, _pw_reason = await check_password_safety(new_pw)
        if not _pw_safe:
            raise HTTPException(status_code=422, detail=_pw_reason)
    except HTTPException:
        raise
    except Exception as _pw_exc:
        logger.warning("Password shield check failed: %s", _pw_exc)

    sf = get_session_factory()
    async with sf() as session:
        db_user = await session.get(User, user_id)
        if not db_user:
            raise HTTPException(status_code=404)
        loop = asyncio.get_running_loop()
        pw_ok = await loop.run_in_executor(None, verify_password, current_pw, db_user.password_hash)
        if not pw_ok:
            raise HTTPException(status_code=401, detail="Current password is incorrect.")
        db_user.password_hash = await loop.run_in_executor(None, get_password_hash, new_pw)
        await session.commit()

        # Audit: password_change
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=user.get("org_id", "-"),
            user_id=user.get("user_id", "-"),
            action="password_change",
            ip_address=client_ip,
            user_agent=user_agent
        ))

    return {"message": "Password changed"}
