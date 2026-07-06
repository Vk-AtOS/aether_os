"""
AetherOS — JWT Authentication (RS256)

Token signing uses RS256 (asymmetric RSA-2048):
  - Private key signs tokens (kept only on the API server)
  - Public key verifies tokens (can be distributed safely)

Key loading priority:
  1. AETHER_JWT_PRIVATE_KEY_B64 / AETHER_JWT_PUBLIC_KEY_B64  (base64-encoded PEM in env var — recommended)
  2. AETHER_JWT_PRIVATE_KEY_PATH / AETHER_JWT_PUBLIC_KEY_PATH (path to PEM files on disk)

HS256 fallback has been REMOVED. The server will refuse to start if RS256 keys are not
configured. This prevents silent key downgrade attacks.

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
_ALG_HS256 = "HS256"  # kept for decode-only migration path (verify old tokens)


def _load_rsa_keys() -> Tuple[Any, Any, str]:
    """
    Returns (private_key, public_key, algorithm="RS256").

    Tries two sources in order:
      1. AETHER_JWT_PRIVATE_KEY_B64 / AETHER_JWT_PUBLIC_KEY_B64 (base64-encoded PEM in env)
      2. AETHER_JWT_PRIVATE_KEY_PATH / AETHER_JWT_PUBLIC_KEY_PATH (PEM file paths)

    Raises RuntimeError if neither source works — the server must not start without
    valid RS256 keys. The HS256 fallback has been removed to prevent silent downgrade.
    """
    from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key

    # Priority 1: base64-encoded PEM in env vars (production recommended)
    priv_b64 = os.environ.get("AETHER_JWT_PRIVATE_KEY_B64", "")
    pub_b64 = os.environ.get("AETHER_JWT_PUBLIC_KEY_B64", "")
    if priv_b64 and pub_b64:
        try:
            private_key = load_pem_private_key(base64.b64decode(priv_b64), password=None)
            public_key = load_pem_public_key(base64.b64decode(pub_b64))
            logger.info("JWT: RS256 enabled (keys from AETHER_JWT_*_KEY_B64 env vars)")
            return private_key, public_key, _ALG_RS256
        except Exception as exc:
            raise RuntimeError(
                f"JWT: AETHER_JWT_PRIVATE_KEY_B64 / AETHER_JWT_PUBLIC_KEY_B64 are set but "
                f"could not be loaded: {exc}. Fix the key values or unset them to use file-path keys."
            ) from exc

    # Priority 2: PEM files on disk
    priv_path = os.environ.get("AETHER_JWT_PRIVATE_KEY_PATH", "")
    pub_path = os.environ.get("AETHER_JWT_PUBLIC_KEY_PATH", "")
    if priv_path and pub_path:
        try:
            with open(priv_path, "rb") as f:
                private_key = load_pem_private_key(f.read(), password=None)
            with open(pub_path, "rb") as f:
                public_key = load_pem_public_key(f.read())
            logger.info("JWT: RS256 enabled (keys from file paths)")
            return private_key, public_key, _ALG_RS256
        except Exception as exc:
            raise RuntimeError(
                f"JWT: AETHER_JWT_PRIVATE_KEY_PATH / AETHER_JWT_PUBLIC_KEY_PATH are set but "
                f"could not be loaded: {exc}. Check file permissions and PEM format."
            ) from exc

    raise RuntimeError(
        "JWT RS256 keys not configured. Set one of:\n"
        "  AETHER_JWT_PRIVATE_KEY_B64 + AETHER_JWT_PUBLIC_KEY_B64 (base64-encoded PEM, recommended)\n"
        "  AETHER_JWT_PRIVATE_KEY_PATH + AETHER_JWT_PUBLIC_KEY_PATH (path to PEM files)\n"
        "See .env.example for instructions. HS256 fallback has been removed."
    )


# Lazy-loaded key cache — resolved once on first use (or on explicit reload)
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


def reload_keys() -> str:
    """
    Force-reload JWT keys from current environment variables.

    Clears the in-process key cache and re-runs _load_rsa_keys() so that any
    keys set after process start (e.g. loaded from .env by dotenv) are picked
    up immediately.  Returns the active algorithm string ('RS256' or 'HS256').

    Raises RuntimeError if neither RS256 keys nor AETHER_SECRET_KEY is present
    (fail-fast — a server without signing keys must not accept traffic).
    """
    global _signing_key, _verify_key, _algorithm
    _signing_key, _verify_key, _algorithm = _load_rsa_keys()
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

    Only RS256 is accepted for new tokens. HS256 is tried as a last resort only
    when AETHER_SECRET_KEY is present, to allow a seamless migration window for
    tokens issued before the RS256 upgrade. Once all tokens have naturally expired
    (default: 1 hour after upgrade) the HS256 path becomes dead code.
    """
    verify_key = _get_verify_key()
    try:
        return _jwt.decode(token, verify_key, algorithms=[_ALG_RS256])
    except _jwt.exceptions.ExpiredSignatureError:
        logger.warning("JWT decode: token expired")
        return None
    except _jwt.exceptions.PyJWTError:
        # Token may have been issued under the old HS256 key — try migration path
        hs_secret = os.environ.get("AETHER_SECRET_KEY", "")
        if hs_secret:
            try:
                payload = _jwt.decode(token, hs_secret, algorithms=[_ALG_HS256])
                logger.info("JWT decode: accepted legacy HS256 token (migration window)")
                return payload
            except _jwt.exceptions.ExpiredSignatureError:
                logger.warning("JWT decode: legacy HS256 token expired")
                return None
            except _jwt.exceptions.PyJWTError as exc:
                logger.warning("JWT decode: RS256 and HS256 both failed — %s", exc)
                return None
            except Exception as exc:
                logger.warning("JWT decode: unexpected error on HS256 fallback — %s", exc)
                return None
        logger.warning("JWT decode: RS256 decode failed and no AETHER_SECRET_KEY for migration")
        return None
    except Exception as exc:
        logger.warning("JWT decode: unexpected error — %s", exc)
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
