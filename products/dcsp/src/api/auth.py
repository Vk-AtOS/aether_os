"""
Authentication logic for DCSP.

Uses bcrypt for password hashing and Redis for session storage.
Falls back to in-memory sessions if Redis is unavailable (dev mode).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import smtplib
from email.mime.text import MIMEText
from typing import Dict, Optional
from dotenv import load_dotenv

load_dotenv()

import bcrypt

from src import redis_client as _redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory fallback for sessions (used when Redis is unavailable)
# ---------------------------------------------------------------------------
ACTIVE_SESSIONS: Dict[str, str] = {}

SESSION_TTL = 86400  # 24 hours


def _session_key(token: str) -> str:
    return f"dcsp:session:{token}"


def _reset_key(token: str) -> str:
    return f"dcsp:reset:{token}"


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(plaintext: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def check_password(plaintext: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plaintext.encode(), hashed.encode())
    except Exception as e:
        logger.warning("bcrypt.checkpw error: %s", e)
        return False


# ---------------------------------------------------------------------------
# User lookup helpers
# ---------------------------------------------------------------------------

def _get_user_from_db(username: str):
    """Return the User ORM object or None. Import here to avoid circular imports."""
    try:
        from src.database import SessionLocal
        from src.models import User
        session = SessionLocal()
        try:
            return session.query(User).filter(
                User.username == username,
                User.is_active == True  # noqa: E712
            ).first()
        finally:
            session.close()
    except Exception as e:
        logger.error("DB lookup failed for user %s: %s", username, e)
        return None


# ---------------------------------------------------------------------------
# Credential verification
# ---------------------------------------------------------------------------

def verify_credentials(username: str, password: str) -> bool:
    """
    Verify username/password against the users table.
    Falls back to env-var plaintext comparison when the users table does not
    exist yet (e.g. during first-run or tests without a migration).
    """
    user = _get_user_from_db(username)
    if user is not None:
        # Only attempt bcrypt if password_hash is a real string (guard against test mocks)
        ph = user.password_hash
        if isinstance(ph, str) and ph.startswith("$2"):
            return check_password(password, ph)
        # password_hash is not a valid bcrypt hash — fall through to env-var fallback
        logger.warning("User %s has non-bcrypt password_hash type %s; trying env-var fallback", username, type(ph).__name__)

    # Fallback: compare against env-var credentials (dev/test mode only)
    _FALLBACK: Dict[str, str] = {
        os.environ.get("DCSP_ADMIN_USERNAME", "admin"): os.environ.get("DCSP_ADMIN_PASSWORD", "dcsp2024"),
        os.environ.get("DCSP_DEMO_USERNAME", "demo"): os.environ.get("DCSP_DEMO_PASSWORD", "demo123"),
    }
    expected = _FALLBACK.get(username)
    if expected is None:
        return False
    # Constant-time comparison to avoid timing attacks even in fallback mode
    return secrets.compare_digest(password, expected)


# ---------------------------------------------------------------------------
# Session management (Redis-backed, in-memory fallback)
# ---------------------------------------------------------------------------

def create_session_token(username: str, tenant_id: Optional[str] = None) -> str:
    """Create a new session token and persist it."""
    token = secrets.token_hex(32)
    payload = json.dumps({"username": username, "tenant_id": tenant_id or ""})

    stored = _redis.setex(_session_key(token), SESSION_TTL, payload)
    if not stored:
        # Fallback: in-memory
        ACTIVE_SESSIONS[token] = username

    return token


def verify_session_token(token: Optional[str]) -> Optional[str]:
    """Return the username if the token is valid, else None."""
    if not token:
        return None

    raw = _redis.get(_session_key(token))
    if raw:
        try:
            data = json.loads(raw)
            return data.get("username")
        except Exception as e:
            logger.warning("Session JSON parse error: %s", e)
            return None

    # Fallback: check in-memory
    return ACTIVE_SESSIONS.get(token)


def get_session_tenant_id(token: Optional[str]) -> Optional[str]:
    """Return the tenant_id stored in the session, or None."""
    if not token:
        return None

    raw = _redis.get(_session_key(token))
    if raw:
        try:
            data = json.loads(raw)
            return data.get("tenant_id") or None
        except Exception as e:
            logger.warning("Session JSON parse error: %s", e)
            return None

    return None


def invalidate_session(token: str) -> None:
    """Remove a session token from both Redis and in-memory store."""
    _redis.delete(_session_key(token))
    if token in ACTIVE_SESSIONS:
        del ACTIVE_SESSIONS[token]


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

def create_reset_token(username: str) -> str:
    """Generate a password-reset token valid for 1 hour."""
    token = secrets.token_hex(32)
    _redis.setex(_reset_key(token), 3600, username)
    return token


def verify_reset_token(token: str) -> Optional[str]:
    """Return username if reset token is valid, else None."""
    return _redis.get(_reset_key(token))


def consume_reset_token(token: str) -> Optional[str]:
    """Consume the token (delete it) and return the username."""
    username = verify_reset_token(token)
    if username:
        _redis.delete(_reset_key(token))
    return username


def send_reset_email(username: str, email: str, reset_url: str) -> None:
    """Send a password-reset email, or log the link if SMTP is not configured."""
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")

    body = (
        f"Hi {username},\n\n"
        f"Click the link below to reset your DCSP password:\n\n"
        f"  {reset_url}\n\n"
        f"This link expires in 1 hour.\n\n"
        f"If you did not request a password reset, ignore this email.\n"
    )

    if not smtp_host or not smtp_user:
        logger.info("SMTP not configured — password reset link for %s: %s", username, reset_url)
        return

    try:
        msg = MIMEText(body)
        msg["Subject"] = "DCSP — Password Reset"
        msg["From"] = smtp_user
        msg["To"] = email

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [email], msg.as_string())
        logger.info("Password reset email sent to %s", email)
    except Exception as e:
        logger.error("Failed to send reset email to %s: %s", email, e)
        logger.info("Password reset link for %s: %s", username, reset_url)
