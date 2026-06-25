from fastapi.testclient import TestClient
from src.api.main import app
from src.api.auth import ACTIVE_SESSIONS
import pytest

client = TestClient(app)

@pytest.fixture
def auth_cookie():
    # Simulate a logged-in user
    token = "test_token_analytics"
    ACTIVE_SESSIONS[token] = "admin"
    return {"session_token": token}

def test_analytics_endpoint_requires_auth():
    # By default TestClient follows redirects to login page (200 OK)
    # Check that we are redirected to login
    response = client.get("/dashboard/analytics", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["location"]

def test_analytics_api_returns_correct_fields(auth_cookie):
    response = client.get("/api/analytics", cookies=auth_cookie)
    assert response.status_code == 200
    data = response.json()
    
    assert "total_jobs" in data
    assert "success_rate" in data
    assert "hours_saved" in data
    assert "cost_saved" in data
    assert "jobs_per_day" in data
    assert "per_repo" in data
    assert "top_errors" in data
    assert "memory_hit_count" in data
    assert "slm_count" in data

def test_analytics_cost_calculation(auth_cookie):
    response = client.get("/api/analytics", cookies=auth_cookie)
    assert response.status_code == 200
    data = response.json()
    
    # Check if cost saved is 150 * hours saved
    assert data["cost_saved"] == data["hours_saved"] * 150

def test_analytics_per_repo_breakdown(auth_cookie):
    response = client.get("/api/analytics", cookies=auth_cookie)
    assert response.status_code == 200
    data = response.json()
    
    per_repo = data["per_repo"]
    assert isinstance(per_repo, list)
    if len(per_repo) > 0:
        repo = per_repo[0]
        assert "repo_name" in repo
        assert "total" in repo
        assert "success_rate" in repo
        assert "avg_confidence" in repo
