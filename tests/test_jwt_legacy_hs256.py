"""KAN-69 F10: in RS256 mode a token signed with the shared HS256 secret must be refused unless the
migration switch AETHER_ACCEPT_LEGACY_HS256_TOKENS is on."""
from __future__ import annotations

import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from aether_os.gateway import auth

SECRET = "s" * 40


@pytest.fixture
def rs256(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setenv("AETHER_JWT_PRIVATE_KEY_B64", base64.b64encode(priv).decode())
    monkeypatch.setenv("AETHER_JWT_PUBLIC_KEY_B64", base64.b64encode(pub).decode())
    monkeypatch.setenv("AETHER_SECRET_KEY", SECRET)
    monkeypatch.delenv("AETHER_ACCEPT_LEGACY_HS256_TOKENS", raising=False)
    assert auth.reload_keys() == "RS256"
    yield
    monkeypatch.undo()
    try:
        auth.reload_keys()
    except RuntimeError:
        pass


def _forged():
    return jwt.encode({"sub": "1", "role": "superadmin", "exp": int(time.time()) + 600}, SECRET, algorithm="HS256")


def test_hs256_token_is_refused_in_rs256_mode_by_default(rs256):
    assert auth.decode_access_token(_forged()) is None
    assert auth.decode_access_token(auth.create_access_token({"sub": "1"}))["sub"] == "1"


def test_migration_switch_accepts_legacy_tokens(rs256, monkeypatch):
    monkeypatch.setenv("AETHER_ACCEPT_LEGACY_HS256_TOKENS", "1")
    assert auth.decode_access_token(_forged())["role"] == "superadmin"
