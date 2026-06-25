from fastapi.testclient import TestClient
from src.api.main import app
from src.api.auth import ACTIVE_SESSIONS
import pytest

client = TestClient(app)

@pytest.fixture
def auth_cookie():
    token = "tenant_api_token"
    ACTIVE_SESSIONS[token] = "admin"
    return {"session_token": token}

def test_create_tenant_api(auth_cookie):
    import uuid
    name = f"API Tenant {uuid.uuid4().hex[:6]}"
    response = client.post(
        "/admin/tenants",
        json={"name": name, "plan": "pro"},
        cookies=auth_cookie
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == name
    assert data["plan"] == "pro"
    assert "id" in data
    assert "slug" in data

def test_list_tenants_api(auth_cookie):
    response = client.get(
        "/admin/tenants",
        cookies=auth_cookie
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

def test_get_tenant_by_id_api(auth_cookie):
    import uuid
    name = f"GetById {uuid.uuid4().hex[:6]}"
    create_res = client.post(
        "/admin/tenants",
        json={"name": name},
        cookies=auth_cookie
    )
    tenant_id = create_res.json()["id"]
    response = client.get(
        f"/admin/tenants/{tenant_id}",
        cookies=auth_cookie
    )
    assert response.status_code == 200
    assert response.json()["id"] == tenant_id

def test_update_tenant_plan_api(auth_cookie):
    import uuid
    name = f"PlanUpdate {uuid.uuid4().hex[:6]}"
    create_res = client.post(
        "/admin/tenants",
        json={"name": name, "plan": "free"},
        cookies=auth_cookie
    )
    tenant_id = create_res.json()["id"]
    response = client.patch(
        f"/admin/tenants/{tenant_id}/plan",
        json={"plan": "enterprise"},
        cookies=auth_cookie
    )
    assert response.status_code == 200
    assert response.json()["plan"] == "enterprise"

def test_delete_tenant_api(auth_cookie):
    import uuid
    name = f"ToDelete {uuid.uuid4().hex[:6]}"
    create_res = client.post(
        "/admin/tenants",
        json={"name": name},
        cookies=auth_cookie
    )
    tenant_id = create_res.json()["id"]
    response = client.delete(
        f"/admin/tenants/{tenant_id}",
        cookies=auth_cookie
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

def test_get_nonexistent_tenant_api(auth_cookie):
    response = client.get(
        "/admin/tenants/nonexistent-000",
        cookies=auth_cookie
    )
    assert response.status_code == 404

def test_admin_dashboard_page(auth_cookie):
    response = client.get(
        "/dashboard/admin",
        cookies=auth_cookie
    )
    assert response.status_code == 200
    assert "Administration" in response.text
    assert "Tenants" in response.text

def test_tenants_api_requires_auth():
    response = client.get(
        "/admin/tenants",
        follow_redirects=False
    )
    assert response.status_code in [401, 403, 302, 303, 307] # Starlette auth might redirect
