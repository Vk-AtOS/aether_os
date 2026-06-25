from fastapi.testclient import TestClient
from src.api.main import app
from src.api.auth import ACTIVE_SESSIONS
import pytest

client = TestClient(app)

@pytest.fixture
def auth_cookie():
    token = "apikey_router_token"
    ACTIVE_SESSIONS[token] = "admin"
    return {"session_token": token}

def test_create_api_key_endpoint(auth_cookie):
    response = client.post(
        "/admin/api-keys",
        json={"name": "Test CI Key",
              "tenant_slug": "default"},
        cookies=auth_cookie
    )
    assert response.status_code == 200
    data = response.json()
    assert "key" in data
    assert data["key"].startswith("dcsp_")
    assert "warning" in data
    assert data["key_prefix"] == data["key"][:8]

def test_created_key_shown_once(auth_cookie):
    """Key value only in create response, not in list."""
    create_res = client.post(
        "/admin/api-keys",
        json={"name": "Once Key",
              "tenant_slug": "default"},
        cookies=auth_cookie
    )
    raw_key = create_res.json()["key"]
    
    list_res = client.get(
        "/admin/api-keys?tenant_slug=default",
        cookies=auth_cookie
    )
    listed = list_res.json()
    for k in listed:
        assert "key" not in k

def test_list_api_keys_endpoint(auth_cookie):
    client.post(
        "/admin/api-keys",
        json={"name": "List Test Key",
              "tenant_slug": "default"},
        cookies=auth_cookie
    )
    response = client.get(
        "/admin/api-keys?tenant_slug=default",
        cookies=auth_cookie
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

def test_revoke_api_key_endpoint(auth_cookie):
    create_res = client.post(
        "/admin/api-keys",
        json={"name": "Revoke This",
              "tenant_slug": "default"},
        cookies=auth_cookie
    )
    key_id = create_res.json()["id"]
    response = client.delete(
        f"/admin/api-keys/{key_id}?tenant_slug=default",
        cookies=auth_cookie
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

def test_revoke_nonexistent_key(auth_cookie):
    response = client.delete(
        "/admin/api-keys/nonexistent-key-000?tenant_slug=default",
        cookies=auth_cookie
    )
    assert response.status_code == 404

def test_create_key_invalid_tenant(auth_cookie):
    response = client.post(
        "/admin/api-keys",
        json={"name": "Bad Tenant Key",
              "tenant_slug": "no-such-tenant"},
        cookies=auth_cookie
    )
    assert response.status_code == 404

def test_api_key_page_loads(auth_cookie):
    response = client.get(
        "/dashboard/api-keys",
        cookies=auth_cookie
    )
    assert response.status_code == 200
    assert "API Keys" in response.text
    assert "Generate Key" in response.text

def test_api_keys_require_auth():
    response = client.get(
        "/admin/api-keys",
        follow_redirects=False
    )
    assert response.status_code in [401, 403, 302, 303, 307]
