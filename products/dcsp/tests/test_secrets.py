from __future__ import annotations
import pytest
import os
from src.secrets.secret_manager import (
    get_secret,
    set_local_secret,
    delete_local_secret,
    list_secret_keys,
    rotate_secret,
    is_vault_enabled,
    clear_cache,
    SecretResult,
    _SECRET_CACHE,
    _LOCAL_SECRETS
)

@pytest.fixture(autouse=True)
def clear_state():
    _SECRET_CACHE.clear()
    _LOCAL_SECRETS.clear()
    yield
    _SECRET_CACHE.clear()
    _LOCAL_SECRETS.clear()

def test_vault_disabled_by_default():
    assert is_vault_enabled() is False

def test_set_and_get_local_secret():
    set_local_secret("db_pass", "hunter2")
    result = get_secret("db_pass")
    assert result.found is True
    assert result.value == "hunter2"
    assert result.source in ("cache", "local")

def test_get_missing_secret():
    result = get_secret("nonexistent_key")
    assert result.found is False
    assert result.value is None
    assert result.source == "not_found"

def test_delete_local_secret():
    set_local_secret("temp_key", "temp_val")
    ok = delete_local_secret("temp_key")
    assert ok is True
    result = get_secret("temp_key")
    assert result.found is False

def test_delete_nonexistent():
    ok = delete_local_secret("ghost_key")
    assert ok is False

def test_list_secret_keys():
    set_local_secret("key_a", "val_a")
    set_local_secret("key_b", "val_b")
    keys = list_secret_keys()
    assert "key_a" in keys
    assert "key_b" in keys

def test_rotate_secret():
    set_local_secret("api_key", "old_value")
    ok = rotate_secret("api_key", "new_value")
    assert ok is True
    result = get_secret("api_key")
    assert result.value == "new_value"

def test_cache_hit():
    set_local_secret("cached_k", "cached_v")
    # First get populates cache
    get_secret("cached_k")
    # Second get should hit cache
    result = get_secret("cached_k")
    assert result.found is True
    assert result.source == "cache"

def test_clear_cache():
    set_local_secret("k1", "v1")
    get_secret("k1")
    clear_cache()
    assert "k1" not in _SECRET_CACHE

def test_secret_result_dataclass():
    r = SecretResult(
        key="x", value="y",
        source="env", found=True)
    assert r.key == "x"
    assert r.found is True

def test_env_fallback(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "fromenv")
    result = get_secret("my_secret")
    assert result.found is True
    assert result.value == "fromenv"
    assert result.source == "env"

def test_secrets_status_api():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "secrets_status_tok"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/api/secrets/status",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    data = r.json()
    assert "vault_enabled" in data
    assert "secret_count" in data

def test_set_secret_api():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "secrets_set_tok"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.post(
        "/api/secrets/set",
        json={"key": "test_k",
              "value": "test_v"},
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    assert r.json()["set"] is True

def test_rotate_secret_api():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "secrets_rot_tok"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.post(
        "/api/secrets/rotate",
        json={"key": "rot_k",
              "value": "rot_v2"},
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    assert r.json()["rotated"] is True
