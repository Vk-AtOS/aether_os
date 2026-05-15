"""
AetherOS — JWT Authentication
Migrated from Aether-one/aetherone/identity.py (JWT layer) + DCSP auth.
Bug 4 fix applied: SECRET_KEY raises RuntimeError if not set in env.
"""
from __future__ import annotations
import logging
import os
import secrets
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_SECRET_KEY_ENV = "AETHER_SECRET_KEY"
_ALGORITHM = "HS256"


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def generate_api_key() -> str:
    """Generate a new API key with the aesk_ prefix."""
    return f"aesk_{secrets.token_hex(16)}"


def hash_api_key(api_key: str) -> str:
    """Hash an API key for DB storage and lookup.

    Uses SHA-256 (not bcrypt) because the key has 128-bit entropy from
    secrets.token_hex(16) — making preimage attacks computationally infeasible.
    Bcrypt cannot be used here since it is non-deterministic and the hash is
    used as a DB lookup key (WHERE key_hash = ?).
    """
    import hashlib
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    """Verify an API key. Supports bcrypt hashes and SHA-256 hashes."""
    if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
        try:
            return bcrypt.checkpw(raw_key.encode(), stored_hash.encode())
        except Exception:
            return False
    import hashlib
    return hashlib.sha256(raw_key.encode()).hexdigest() == stored_hash


def _get_secret_key() -> str:
    """
    Bug 4 fix: No hardcoded fallback for SECRET_KEY.
    Raises RuntimeError if AETHER_SECRET_KEY is not set.
    """
    key = os.environ.get(_SECRET_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"JWT secret key not configured. "
            f"Set the {_SECRET_KEY_ENV} environment variable to a strong random secret."
        )
    return key


def create_refresh_token(data: Dict[str, Any], expires_days: int = 30) -> str:
    """Create a long-lived refresh token (30 days). Must not be used as an access token."""
    return create_access_token(
        {**data, "token_type": "refresh"},
        expires_hours=expires_days * 24,
    )


def create_access_token(
    data: Dict[str, Any],
    expires_hours: int = 168,  # 7 days default — avoids 80K simultaneous re-login storms
) -> str:
    """Create a signed JWT access token."""
    import uuid as _uuid
    try:
        from jose import jwt  # type: ignore
    except ImportError as exc:
        raise ImportError("python-jose not installed. Run: pip install python-jose[cryptography]") from exc

    payload = dict(data)
    expire = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    payload["exp"] = expire
    payload["iat"] = datetime.now(timezone.utc)
    payload.setdefault("jti", str(_uuid.uuid4()))  # unique token ID for blacklisting
    return jwt.encode(payload, _get_secret_key(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify a JWT token. Returns None if invalid."""
    try:
        from jose import jwt, JWTError  # type: ignore
        return jwt.decode(token, _get_secret_key(), algorithms=[_ALGORITHM])
    except Exception as exc:
        logger.debug("Token decode failed: %s", exc)
        return None


def verify_token_dependency(token: str) -> Dict[str, Any]:
    """
    FastAPI dependency: verifies token and returns claims.
    Raises HTTPException 401 if invalid.
    """
    from fastapi import HTTPException, status
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload
