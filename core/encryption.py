"""
AetherOS field-level encryption for sensitive DB columns.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` package.
Key must be a URL-safe base64-encoded 32-byte value supplied via AETHER_FIELD_KEY.
Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If AETHER_FIELD_KEY is not set, a per-process ephemeral key is used as a safe
fallback (data written in one process cannot be decrypted by another — this will
cause errors in multi-worker deployments and is logged as a warning on startup).
"""
from __future__ import annotations
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, Text
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        raw = os.environ.get("AETHER_FIELD_KEY", "")
        if raw:
            _fernet = Fernet(raw.encode())
        else:
            logger.warning(
                "AETHER_FIELD_KEY not set — using ephemeral encryption key. "
                "Encrypted fields will not survive process restarts. "
                "Set AETHER_FIELD_KEY in production."
            )
            _fernet = Fernet(Fernet.generate_key())
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a string value; returns a URL-safe base64 ciphertext string."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a ciphertext string; raises ValueError on tampered/invalid data."""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Field decryption failed — data may be corrupt or key rotated") from exc


class EncryptedText(TypeDecorator):
    """SQLAlchemy column type that transparently encrypts on write and decrypts on read."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return encrypt(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        try:
            return decrypt(value)
        except ValueError:
            logger.error("EncryptedText: failed to decrypt DB value — returning None")
            return None
