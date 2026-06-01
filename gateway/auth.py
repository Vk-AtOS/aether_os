"""
AetherOS — JWT Authentication (RS256)

Token signing uses RS256 (asymmetric RSA-2048):
  - Private key signs tokens (kept only on the API server)
  - Public key verifies tokens (can be distributed safely)

Key loading priority:
  1. AETHER_JWT_PRIVATE_KEY_B64 / AETHER_JWT_PUBLIC_KEY_B64  (base64-encoded PEM in env var — recommended)
  2. AETHER_JWT_PRIVATE_KEY_PATH / AETHER_JWT_PUBLIC_KEY_PATH (path to PEM files on disk)
  3. AETHER_SECRET_KEY fallback → HS256 (legacy; logs a deprecation warning on startup)

Generate a new keypair:
  openssl genrsa -out jwt_private.pem 2048
  openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
  # Then base64-encode for env var storage:
  python3 -c "import base64; print(base64.b64encode(open('jwt_private.pem','rb').read()).decode())"
  python3 -c "import base64; print(base64.b64encode(open('jwt_public.pem','rb').read()).decode())"
"""
from __future__ import annotations
import base64
import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import bcrypt
import jwt as _jwt  # PyJWT

logger = logging.getLogger(__name__)

# ── Algorithm selection ────────────────────────────────────────────────────────

_ALG_RS256 = "RS256"
_ALG_HS256 = "HS256"  # legacy fallback only


def _load_rsa_keys() -> Tuple[Optional[Any], Optional[Any], str]:
    """
    Returns (private_key_or_secret, public_key_or_secret, algorithm).
    Prefers RS256 with RSA keys; falls back to HS256 with AETHER_SECRET_KEY.
    """
    # Priority 1: base64-encoded PEM in env vars (production recommended)
    priv_b64 = os.environ.get("AETHER_JWT_PRIVATE_KEY_B64", "")
    pub_b64 = os.environ.get("AETHER_JWT_PUBLIC_KEY_B64", "")
    if priv_b64 and pub_b64:
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
            private_key = load_pem_private_key(base64.b64decode(priv_b64), password=None)
            public_key = load_pem_public_key(base64.b64decode(pub_b64))
            logger.info("JWT: RS256 enabled (keys from AETHER_JWT_*_KEY_B64 env vars)")
            return private_key, public_key, _ALG_RS256
        except Exception as exc:
            logger.error("JWT: Failed to load RS256 keys from B64 env vars: %s — falling back to HS256", exc)

    # Priority 2: PEM files on disk
    priv_path = os.environ.get("AETHER_JWT_PRIVATE_KEY_PATH", "")
    pub_path = os.environ.get("AETHER_JWT_PUBLIC_KEY_PATH", "")
    if priv_path and pub_path:
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
            with open(priv_path, "rb") as f:
                private_key = load_pem_private_key(f.read(), password=None)
            with open(pub_path, "rb") as f:
                public_key = load_pem_public_key(f.read())
            logger.info("JWT: RS256 enabled (keys from file paths)")
            return private_key, public_key, _ALG_RS256
        except Exception as exc:
            logger.error("JWT: Failed to load RS256 keys from files: %s — falling back to HS256", exc)

    # Priority 3: HS256 legacy fallback
    hs_secret = os.environ.get("AETHER_SECRET_KEY", "")
    if hs_secret:
        logger.warning(
            "JWT: Using HS256 (AETHER_SECRET_KEY). "
            "Upgrade to RS256 by setting AETHER_JWT_PRIVATE_KEY_B64 and AETHER_JWT_PUBLIC_KEY_B64. "
            "HS256 is symmetric — the signing secret must never leave the server."
        )
        return hs_secret, hs_secret, _ALG_HS256

    raise RuntimeError(
        "JWT keys not configured. Set AETHER_JWT_PRIVATE_KEY_B64 + AETHER_JWT_PUBLIC_KEY_B64 "
        "(RS256, recommended) or AETHER_SECRET_KEY (HS256, legacy). "
        "See .env.example for instructions."
    )


# Lazy-loaded key cache — resolved once on first use
_signing_key: Any = None
_verify_key: Any = None
_algorithm: str = _ALG_RS256


def _get_signing_key() -> Any:
    global _signing_key, _verify_key, _algorithm
    if _signing_key is None:
        _signing_key, _verify_key, _algorithm = _load_rsa_keys()
    return _signing_key


def _get_verify_key() -> Any:
    _get_signing_key()  # ensure loaded
    return _verify_key


def get_algorithm() -> str:
    _get_signing_key()  # ensure loaded
    return _algorithm


# ── Password utilities ─────────────────────────────────────────────────────────

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


# ── API key utilities ──────────────────────────────────────────────────────────

def generate_api_key() -> str:
    return f"aesk_{secrets.token_hex(16)}"


def hash_api_key(api_key: str) -> str:
    """SHA-256 hash of API key for DB storage (deterministic lookup)."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
        try:
            return bcrypt.checkpw(raw_key.encode(), stored_hash.encode())
        except Exception as exc:
            logger.warning("API key bcrypt verification error: %s", exc)
            return False
    return hashlib.sha256(raw_key.encode()).hexdigest() == stored_hash


# ── Token creation ─────────────────────────────────────────────────────────────

def create_refresh_token(data: Dict[str, Any], expires_days: int = 30) -> str:
    """30-day refresh token. Must not be accepted as an access token."""
    return create_access_token(
        {**data, "token_type": "refresh"},
        expires_hours=expires_days * 24,
    )


def create_access_token(
    data: Dict[str, Any],
    expires_hours: int = 1,
) -> str:
    """Create a signed JWT. Uses RS256 when RSA keys are configured, HS256 as fallback."""
    payload = dict(data)
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    payload["iat"] = datetime.now(timezone.utc)
    payload.setdefault("jti", str(uuid.uuid4()))
    return _jwt.encode(payload, _get_signing_key(), algorithm=get_algorithm())


# ── Token verification ─────────────────────────────────────────────────────────

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode and verify a JWT. Returns None if expired or invalid.
    Accepts both RS256 (current) and HS256 (legacy) tokens during migration.
    """
    alg = get_algorithm()
    # When RS256 is active, also try HS256 for tokens issued before the migration.
    algorithms = [alg, _ALG_HS256] if alg == _ALG_RS256 else [_ALG_HS256]

    last_exc: Optional[Exception] = None
    for algorithm in algorithms:
        verify_key = _get_verify_key() if algorithm == _ALG_RS256 else os.environ.get("AETHER_SECRET_KEY", "")
        try:
            return _jwt.decode(token, verify_key, algorithms=[algorithm])
        except _jwt.exceptions.ExpiredSignatureError:
            logger.warning("JWT decode: token expired (alg=%s)", algorithm)
            return None
        except _jwt.exceptions.PyJWTError as exc:
            last_exc = exc
            continue
        except Exception as exc:
            last_exc = exc
            continue

    logger.warning("JWT decode: all algorithms failed — %s", last_exc)
    return None


def verify_token_dependency(token: str) -> Dict[str, Any]:
    """FastAPI dependency: raises HTTP 401 if token is invalid."""
    from fastapi import HTTPException, status
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload
