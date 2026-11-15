"""
Unit tests for gateway/auth.py (security module)

Tests use real bcrypt and real PyJWT — security primitives must not be mocked.
Covers password hashing, JWT round-trips, and expired token handling.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

# We test against real bcrypt and real JWT — no mocking of crypto primitives.
import jwt as _jwt


# ---------------------------------------------------------------------------
# Ensure HS256 fallback is available for tests (no RSA key needed in CI)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def use_hs256_in_tests(monkeypatch):
    """
    Override JWT key env to use HS256 in unit tests so no RSA key file
    is required. This is the documented fallback mode.
    """
    monkeypatch.setenv("AETHER_SECRET_KEY", "test-secret-key-for-unit-tests-only")
    monkeypatch.delenv("AETHER_JWT_PRIVATE_KEY_B64", raising=False)
    monkeypatch.delenv("AETHER_JWT_PUBLIC_KEY_B64", raising=False)
    monkeypatch.delenv("AETHER_JWT_PRIVATE_KEY_PATH", raising=False)
    monkeypatch.delenv("AETHER_JWT_PUBLIC_KEY_PATH", raising=False)

    # Reset cached keys so the monkeypatched env is picked up
    import aether_os.gateway.auth as auth_mod
    auth_mod._signing_key = None
    auth_mod._verify_key = None
    auth_mod._algorithm = auth_mod._ALG_RS256  # will be reset by _load_rsa_keys()
    yield
    # Teardown: reset again so other tests start clean
    auth_mod._signing_key = None
    auth_mod._verify_key = None
    auth_mod._algorithm = auth_mod._ALG_RS256


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_produces_bcrypt_string(self):
        from aether_os.gateway.auth import get_password_hash
        hashed = get_password_hash("mysecret")
        assert hashed.startswith("$2b$")

    def test_verify_correct_password(self):
        from aether_os.gateway.auth import get_password_hash, verify_password
        hashed = get_password_hash("mysecret")
        assert verify_password("mysecret", hashed) is True

    def test_verify_wrong_password(self):
        from aether_os.gateway.auth import get_password_hash, verify_password
        hashed = get_password_hash("mysecret")
        assert verify_password("wrongpassword", hashed) is False

    def test_same_password_different_hashes(self):
        """bcrypt generates a random salt so two hashes must differ."""
        from aether_os.gateway.auth import get_password_hash
        h1 = get_password_hash("same")
        h2 = get_password_hash("same")
        assert h1 != h2

    def test_empty_password_can_be_hashed(self):
        """Edge case: empty password must not raise."""
        from aether_os.gateway.auth import get_password_hash, verify_password
        hashed = get_password_hash("")
        assert verify_password("", hashed) is True

    def test_unicode_password(self):
        from aether_os.gateway.auth import get_password_hash, verify_password
        pwd = "päässäkiin🔑"
        hashed = get_password_hash(pwd)
        assert verify_password(pwd, hashed) is True
        assert verify_password("paassaakiin", hashed) is False


# ---------------------------------------------------------------------------
# API key generation and hashing
# ---------------------------------------------------------------------------

class TestApiKeyUtils:
    def test_generate_api_key_format(self):
        from aether_os.gateway.auth import generate_api_key
        key = generate_api_key()
        assert key.startswith("aesk_")
        assert len(key) > 5

    def test_hash_api_key_deterministic(self):
        from aether_os.gateway.auth import hash_api_key
        h1 = hash_api_key("mykey")
        h2 = hash_api_key("mykey")
        assert h1 == h2

    def test_hash_api_key_different_inputs(self):
        from aether_os.gateway.auth import hash_api_key
        assert hash_api_key("key1") != hash_api_key("key2")

    def test_verify_api_key_sha256_path(self):
        from aether_os.gateway.auth import hash_api_key, verify_api_key
        raw = "myrawkey"
        stored = hash_api_key(raw)
        assert verify_api_key(raw, stored) is True
        assert verify_api_key("wrongkey", stored) is False


# ---------------------------------------------------------------------------
# JWT creation
# ---------------------------------------------------------------------------

class TestCreateAccessToken:
    def test_token_is_decodable(self):
        from aether_os.gateway.auth import create_access_token, decode_access_token
        token = create_access_token({"sub": "user1", "org_id": "org1"})
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "user1"
        assert payload["org_id"] == "org1"

    def test_token_contains_exp_and_iat(self):
        from aether_os.gateway.auth import create_access_token, decode_access_token
        token = create_access_token({"sub": "user1"})
        payload = decode_access_token(token)
        assert "exp" in payload
        assert "iat" in payload

    def test_token_contains_jti(self):
        from aether_os.gateway.auth import create_access_token, decode_access_token
        token = create_access_token({"sub": "user1"})
        payload = decode_access_token(token)
        assert "jti" in payload
        assert len(payload["jti"]) > 0

    def test_two_tokens_have_different_jti(self):
        from aether_os.gateway.auth import create_access_token, decode_access_token
        t1 = create_access_token({"sub": "user1"})
        t2 = create_access_token({"sub": "user1"})
        p1 = decode_access_token(t1)
        p2 = decode_access_token(t2)
        assert p1["jti"] != p2["jti"]

    def test_custom_expiry(self):
        from aether_os.gateway.auth import create_access_token, decode_access_token
        token = create_access_token({"sub": "user1"}, expires_hours=24)
        payload = decode_access_token(token)
        now = time.time()
        assert payload["exp"] > now + 23 * 3600
        assert payload["exp"] < now + 25 * 3600


# ---------------------------------------------------------------------------
# JWT expiry
# ---------------------------------------------------------------------------

class TestTokenExpiry:
    def test_expired_token_returns_none(self, monkeypatch):
        """Tokens with exp in the past must be rejected."""
        from aether_os.gateway.auth import get_algorithm, _get_signing_key
        import aether_os.gateway.auth as auth_mod

        payload = {
            "sub": "user1",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "jti": "test-jti",
        }
        signing_key = _get_signing_key()
        expired_token = _jwt.encode(payload, signing_key, algorithm=get_algorithm())

        result = auth_mod.decode_access_token(expired_token)
        assert result is None

    def test_valid_token_not_expired(self):
        from aether_os.gateway.auth import create_access_token, decode_access_token
        token = create_access_token({"sub": "user1"}, expires_hours=1)
        payload = decode_access_token(token)
        assert payload is not None

    def test_tampered_token_returns_none(self):
        """A token with a modified payload must fail signature verification."""
        from aether_os.gateway.auth import create_access_token, decode_access_token
        token = create_access_token({"sub": "user1"})
        # Tamper with the payload section (second segment)
        parts = token.split(".")
        parts[1] = parts[1] + "XX"
        bad_token = ".".join(parts)
        result = decode_access_token(bad_token)
        assert result is None

    def test_garbage_token_returns_none(self):
        from aether_os.gateway.auth import decode_access_token
        result = decode_access_token("not.a.valid.jwt.token")
        assert result is None


# ---------------------------------------------------------------------------
# Refresh token
# ---------------------------------------------------------------------------

class TestRefreshToken:
    def test_refresh_token_decodable(self):
        from aether_os.gateway.auth import create_refresh_token, decode_access_token
        token = create_refresh_token({"sub": "user1", "org_id": "org1"})
        payload = decode_access_token(token)
        assert payload is not None
        assert payload.get("token_type") == "refresh"

    def test_refresh_token_has_30_day_expiry(self):
        from aether_os.gateway.auth import create_refresh_token, decode_access_token
        token = create_refresh_token({"sub": "user1"})
        payload = decode_access_token(token)
        now = time.time()
        # Should expire roughly 30 days from now (allow ±1h tolerance)
        assert payload["exp"] > now + (30 * 24 - 1) * 3600
        assert payload["exp"] < now + (30 * 24 + 1) * 3600


# ---------------------------------------------------------------------------
# reload_keys
# ---------------------------------------------------------------------------

class TestReloadKeys:
    def test_reload_returns_algorithm_string(self):
        import aether_os.gateway.auth as auth_mod
        alg = auth_mod.reload_keys()
        assert alg in ("RS256", "HS256")

    def test_reload_changes_cached_keys(self):
        import aether_os.gateway.auth as auth_mod
        _ = auth_mod._get_signing_key()  # warm cache
        old_key = auth_mod._signing_key
        auth_mod.reload_keys()
        # After reload with same env, key should be same type/value
        assert auth_mod._signing_key is not None
