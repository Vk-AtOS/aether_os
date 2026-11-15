"""
AetherOS — Admin Service
Business logic for admin operations: user invitation, password reset.
Extracted from admin_router.py (M10) to keep router under 400 lines.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def invite_user_service(
    email: str,
    role: str,
    org_id: str,
    inviter_name: str,
) -> Dict[str, Any]:
    """
    Create a new user with a temporary password, send invite email.
    Returns a dict suitable for the API response.
    Raises HTTPException on validation failures (caller must import HTTPException).
    """
    from fastapi import HTTPException
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from aether_os.gateway.auth import get_password_hash
    from sqlalchemy import select
    import secrets as _sec

    sf = get_session_factory()
    async with sf() as session:
        existing = (await session.execute(
            select(User).where(User.email == email)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="User with this email already exists")

        temp_password = _sec.token_urlsafe(16)
        new_user = User(
            org_id=org_id,
            email=email,
            password_hash=get_password_hash(temp_password),
            role=role,
            is_active=True,
            must_change_password=True,  # FIX-15: invited users must set own password on first login
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
        new_user_id = new_user.id

    # Send invite email
    email_sent = await _send_invite_email(email, temp_password, inviter_name)

    return {
        "id": new_user_id,
        "email": email,
        "role": role,
        "email_sent": email_sent,
        # Only include temp_password when email could not be sent so admin can share it manually
        **({"temp_password": temp_password} if not email_sent else {}),
    }


async def reset_user_password_service(
    user_id: str,
    org_id: str,
    admin_sub: str,
) -> Dict[str, Any]:
    """
    Reset a user's password to a temporary value.  Returns API response dict.
    SEC-H1: temp_password only included in response when email fails.
    FIX-15: sets must_change_password=True.
    """
    from fastapi import HTTPException
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from aether_os.gateway.auth import get_password_hash
    from aether_os.gateway.auth_refresh import revoke_user_sessions
    import secrets as _sec

    sf = get_session_factory()
    async with sf() as session:
        db_user = await session.get(User, user_id)
        if not db_user or db_user.org_id != org_id:
            raise HTTPException(status_code=404, detail="User not found")
        temp_password = _sec.token_urlsafe(16)
        db_user.password_hash = get_password_hash(temp_password)
        db_user.must_change_password = True  # FIX-15: force change on next login
        # The old password is gone, so sessions opened with it must not keep refreshing.
        await revoke_user_sessions(db_user.id)
        await session.commit()
        target_email = db_user.email

    logger.warning(
        "admin_service: admin %s reset password for user %s", admin_sub, user_id
    )

    email_sent = await _send_password_reset_email(target_email, temp_password)

    return {
        "success": True,
        "user_id": user_id,
        "email_sent": email_sent,
        "must_change_password": True,
        # SEC-H1: only expose temp_password when email could NOT be delivered
        **({"temp_password": temp_password} if not email_sent else {}),
    }


# ── Private email helpers ──────────────────────────────────────────────────────

async def _send_invite_email(email: str, temp_password: str, inviter_name: str) -> bool:
    """Send invitation email with temp credentials. Returns True on success."""
    try:
        from aether_os.core.notifications.email import get_email_notifier
        frontend_url = os.environ.get("FRONTEND_URL", "https://app.aetheros.ai").rstrip("/")
        login_url = f"{frontend_url}/login"
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
        return await notifier.send(email, "You've been invited to AetherOS", body_html, body_text)
    except Exception as exc:
        logger.warning("admin_service: invite email failed for %s: %s", email, exc)
        return False


async def _send_password_reset_email(target_email: str, temp_password: str) -> bool:
    """Send password-reset email with new temp credentials. Returns True on success."""
    try:
        from aether_os.core.notifications.email import get_email_notifier
        frontend_url = os.environ.get("FRONTEND_URL", "https://app.aetheros.ai").rstrip("/")
        notifier = get_email_notifier()
        body_html = (
            f"<p>An administrator has reset your AetherOS password.</p>"
            f"<p>Your temporary password is: <code>{temp_password}</code></p>"
            f"<p>You will be required to change it on your next login.</p>"
            f"<p><a href='{frontend_url}/login' style='background:#7c3aed;color:#fff;"
            f"padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block'>Sign In</a></p>"
            f"<hr><p style='color:#888;font-size:12px'>AetherOS</p>"
        )
        body_text = (
            f"An administrator has reset your AetherOS password.\n\n"
            f"Temporary password: {temp_password}\n\n"
            f"You will be required to change it on your next login.\nSign in at: {frontend_url}/login"
        )
        return await notifier.send(
            target_email, "AetherOS: Your password has been reset", body_html, body_text
        )
    except Exception as exc:
        logger.warning("admin_service: password reset email failed for %s: %s", target_email, exc)
        return False
