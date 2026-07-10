"""
AetherOS — Gateway API Tests
Tests FastAPI endpoints.
"""
from __future__ import annotations
import os
import sys
import warnings
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# TestClient wraps an async app in a sync context via anyio. When the test
# process tears down, anyio's internal async generators may emit
# ResourceWarning about unclosed async generators or sockets. These are from
# the test harness, not from production code bugs, and are safe to suppress.
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", message="coroutine .* was never awaited", category=RuntimeWarning)


def _make_app(tmp_path=None):
    """Create a test app with required env vars set."""
    os.environ["AETHER_SECRET_KEY"] = "test-secret-key-32-chars-minimum"
    os.environ["AETHER_ADMIN_EMAIL"] = "admin@aetheros.ai"
    os.environ["AETHER_ADMIN_PASSWORD"] = "admin"
    os.environ["CORS_ORIGINS"] = "http://localhost:3000"

    if tmp_path:
        db_path = str(tmp_path / "test.db")
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

    # Reset singletons before creating app
    import aether_os.core.config.loader as cfg_mod
    cfg_mod.AetherConfig._instance = None

    import aether_os.core.db as db_mod
    db_mod._engine = None
    db_mod._session_factory = None

    import aether_os.core.rate_limiter as _rl_mod
    _rl_mod._mem = _rl_mod._MemoryStore()
    _rl_mod._instance = None
    _rl_mod._redis_available = False   # force in-memory mode so Redis state doesn't bleed
    _rl_mod._async_redis_client = None

    from aether_os.gateway.api import create_app
    return create_app()


@pytest.fixture
def client(tmp_path):
    import sqlite3
    db_path = str(tmp_path / "test.db")
    app = _make_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as c:
        # Mock HIBP password check so common test passwords are accepted
        with patch("aether_os.core.guardian.password_shield.check_password_safety",
                   new_callable=AsyncMock, return_value=(True, "")):
            c.post("/auth/register", json={
                "email": "testadmin@example.com",
                "password": "TestPass@123!",
                "org_name": "Test Org",
                "terms_accepted": True,
                "dpa_accepted": True,
            })
        # Email verification uses Redis (unavailable in tests) so set it directly in the DB.
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE users SET email_verified = 1 WHERE email = ?",
            ("testadmin@example.com",),
        )
        conn.commit()
        conn.close()
        yield c


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "timestamp" in data


def test_login_success(client):
    resp = client.post("/auth/login", json={
        "email": "testadmin@example.com",
        "password": "TestPass@123!",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    resp = client.post("/auth/login", json={
        "email": "testadmin@example.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


def test_protected_endpoint_without_token(client):
    resp = client.get("/pipeline/status/fake-run-id")
    assert resp.status_code in (401, 403), (
        f"Protected route must return 401/403 without auth, got {resp.status_code}"
    )


def test_protected_endpoint_with_token(client):
    # Get token
    login_resp = client.post("/auth/login", json={
        "email": "testadmin@example.com",
        "password": "TestPass@123!",
    })
    assert login_resp.status_code == 200, f"Login failed: {login_resp.status_code} {login_resp.text}"
    token = login_resp.json()["access_token"]

    # Access protected endpoint
    resp = client.get(
        "/pipeline/status/fake-run-id",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 200 means auth passed and run found; 404 means auth passed but run not found
    # 401/403 would mean auth failed — that should not happen with a valid token
    assert resp.status_code in (200, 404), (
        f"Expected 200 or 404 (auth passed), got {resp.status_code}: {resp.text}"
    )


def test_pipeline_start_requires_auth(client):
    resp = client.post("/factory/start", json={
        "requirement": "Build a REST API",
    })
    assert resp.status_code == 401


def test_pipeline_start_with_auth(client, tmp_path):
    import aether_os.core.llm.client as llm_mod
    llm_mod._instance = None

    # Get token
    login_resp = client.post("/auth/login", json={
        "email": "testadmin@example.com",
        "password": "TestPass@123!",
    })
    token = login_resp.json()["access_token"]

    resp = client.post(
        "/factory/start",
        json={"requirement": "Build a hello world app", "project_name": "test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "started"

    llm_mod._instance = None


def test_cors_origins_from_env():
    """Test that CORS origins come from env var, not hardcoded."""
    from aether_os.gateway.api import _get_cors_origins
    os.environ["CORS_ORIGINS"] = "http://example.com,https://app.example.com"
    origins = _get_cors_origins()
    assert "http://example.com" in origins
    assert "https://app.example.com" in origins
    assert "*" not in origins  # Bug 3 fix: never wildcard


def test_cors_default_no_wildcard():
    """Test CORS default is localhost, not wildcard."""
    from aether_os.gateway.api import _get_cors_origins
    old = os.environ.pop("CORS_ORIGINS", None)
    origins = _get_cors_origins()
    assert "*" not in origins
    if old:
        os.environ["CORS_ORIGINS"] = old


# ── Auth module ───────────────────────────────────────────────────────────────

def test_jwt_create_and_decode():
    import importlib
    # Clear any RS256 key env vars so auth falls back to HS256 for this test
    for _k in ("AETHER_JWT_PRIVATE_KEY_B64", "AETHER_JWT_PUBLIC_KEY_B64",
                "AETHER_JWT_PRIVATE_KEY_PATH", "AETHER_JWT_PUBLIC_KEY_PATH"):
        os.environ.pop(_k, None)
    os.environ["AETHER_SECRET_KEY"] = "test-secret-key-32chars-padding!"
    import aether_os.gateway.auth as _auth_mod
    importlib.reload(_auth_mod)  # re-initialize with clean env to pick up HS256 fallback
    from aether_os.gateway.auth import create_access_token, decode_access_token
    token = create_access_token({"sub": "user123", "role": "admin"})
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "user123"
    assert payload["role"] == "admin"


def test_jwt_invalid_token_returns_none():
    os.environ["AETHER_SECRET_KEY"] = "test-secret-key-32-chars"
    from aether_os.gateway.auth import decode_access_token
    result = decode_access_token("invalid.token.here")
    assert result is None


def test_jwt_missing_secret_raises():
    """Test Bug 4 fix: no hardcoded JWT secret."""
    old = os.environ.pop("AETHER_SECRET_KEY", None)
    try:
        from aether_os.gateway import auth as auth_mod
        # Force reload to clear module cache
        import importlib
        importlib.reload(auth_mod)
        with pytest.raises(RuntimeError, match="AETHER_SECRET_KEY"):
            auth_mod.create_access_token({"sub": "test"})
    finally:
        if old:
            os.environ["AETHER_SECRET_KEY"] = old
        import importlib
        import aether_os.gateway.auth as auth_mod
        importlib.reload(auth_mod)


def test_zero_trust_missing_secret_raises():
    """Test Bug 2 fix: no hardcoded zero-trust secret."""
    old = os.environ.pop("AETHER_ONE_ZT_SECRET", None)
    try:
        from aether_os.core.identity import zero_trust
        import importlib
        importlib.reload(zero_trust)
        with pytest.raises(RuntimeError, match="AETHER_ONE_ZT_SECRET"):
            zero_trust.issue_ticket("/project", "/file.py", "python_run")
    finally:
        if old:
            os.environ["AETHER_ONE_ZT_SECRET"] = old
        import importlib
        from aether_os.core.identity import zero_trust
        importlib.reload(zero_trust)
