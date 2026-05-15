"""
AetherOS — Gateway API Tests
Tests FastAPI endpoints.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


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

    from aether_os.gateway.api import create_app
    return create_app()


@pytest.fixture
def client(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as c:
        # Register a default user for login tests
        c.post("/auth/register", json={
            "email": "testadmin@example.com",
            "password": "testpass123",
            "org_name": "Test Org",
            "terms_accepted": True,
            "dpa_accepted": True,
        })
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
        "password": "testpass123",
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
    assert resp.status_code == 401


def test_protected_endpoint_with_token(client):
    # Get token
    login_resp = client.post("/auth/login", json={
        "email": "testadmin@example.com",
        "password": "testpass123",
    })
    assert login_resp.status_code == 200, f"Login failed: {login_resp.status_code} {login_resp.text}"
    token = login_resp.json()["access_token"]

    # Access protected endpoint
    resp = client.get(
        "/pipeline/status/fake-run-id",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 404 is fine — it means auth passed, just run not found
    assert resp.status_code in (200, 404)


def test_pipeline_start_requires_auth(client):
    resp = client.post("/pipeline/start", json={
        "requirement": "Build a REST API",
    })
    assert resp.status_code == 401


def test_pipeline_start_with_auth(client, tmp_path):
    import aether_os.core.llm.client as llm_mod
    llm_mod._instance = None

    # Get token
    login_resp = client.post("/auth/login", json={
        "email": "testadmin@example.com",
        "password": "testpass123",
    })
    token = login_resp.json()["access_token"]

    resp = client.post(
        "/pipeline/start",
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
    os.environ["AETHER_SECRET_KEY"] = "test-secret-key-32-chars"
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
