"""
Tests for DCSP API endpoints.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.api.state import JOB_HISTORY, add_job_to_history
from unittest.mock import patch

client = TestClient(app)

def get_auth_token():
    """Helper to get a valid session token."""
    response = client.post("/auth/login", data={"username": "admin", "password": "dcsp2024"}, follow_redirects=False)
    return response.cookies.get("session_token")

@pytest.fixture
def auth_client():
    """Provides a TestClient with a session token set."""
    token = get_auth_token()
    client.cookies.set("session_token", token)
    yield client
    client.cookies.delete("session_token")

@pytest.fixture(autouse=True)
def clear_job_history():
    """Clear in-memory job history before and after each test."""
    JOB_HISTORY.clear()
    yield
    JOB_HISTORY.clear()

@pytest.fixture(autouse=True)
def mock_db_global():
    """Mock all database-related calls globally for API tests."""
    with patch("src.api.main.create_all_tables"), \
         patch("src.database.SessionLocal") as mock_session_local, \
         patch("src.api.webhook.get_db") as mock_get_db:

        mock_session = mock_session_local.return_value
        # Mock common query patterns
        mock_session.query.return_value.all.return_value = []
        mock_session.query.return_value.filter.return_value.all.return_value = []
        mock_session.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_session.query.return_value.scalar.return_value = 0

        # Mock get_db dependency
        mock_get_db.return_value = mock_session

        yield mock_session

def test_health_check():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "environment" in data
    assert "database" in data
    assert "redis" in data
    assert "bedrock" in data

def test_dashboard_endpoint(auth_client):
    """Test dashboard HTML endpoint with auth."""
    response = auth_client.get("/dashboard")
    assert response.status_code == 200
    # The main dashboard template contains the title in the <title> tag
    assert "DCSP" in response.text
    assert "Logged in as:" in response.text

def test_metrics_endpoint_empty(auth_client):
    """Test metrics endpoint with no jobs and auth."""
    # Force fallback to in-memory state for this test to use JOB_HISTORY
    with patch("src.api.dashboard_jobs.SessionLocal", side_effect=Exception("Fallback")):
        response = auth_client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["total_jobs"] == 0
        assert data["success_rate"] == 0.0
        assert data["recent_jobs"] == []
        # Check CORS
        assert response.headers["Access-Control-Allow-Origin"] == "*"

def test_metrics_endpoint_with_data(auth_client):
    """Test metrics endpoint with jobs and auth."""
    JOB_HISTORY.clear()

    JOB_HISTORY.append({
        "id": "1",
        "timestamp": "2026-03-06T12:00:00Z",
        "repo_name": "test-repo",
        "branch": "main",
        "success": True,
        "confidence": 0.85,
        "escalated": False,
        "explanation": "Fixed bug",
        "approved": None, "ci_system": None, "detected_language": None, "patch_diff": None, "violations": [], "slm_generated": False, "approved_pr_url": None, "source": "slm", "fingerprint": ""
    })
    JOB_HISTORY.append({
        "id": "2",
        "timestamp": "2026-03-06T12:01:00Z",
        "repo_name": "other-repo",
        "branch": "dev",
        "success": False,
        "confidence": 0.4,
        "escalated": True,
        "explanation": "Could not localize",
        "approved": None, "ci_system": None, "detected_language": None, "patch_diff": None, "violations": [], "slm_generated": False, "approved_pr_url": None, "source": "slm", "fingerprint": ""
    })

    # Force fallback to in-memory state for this test to use JOB_HISTORY
    with patch("src.api.dashboard_jobs.SessionLocal", side_effect=Exception("Fallback")):
        response = auth_client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["total_jobs"] == 2
        assert data["success_rate"] == 0.5
        assert data["escalation_rate"] == 0.5
        assert data["avg_confidence"] == pytest.approx((0.85 + 0.4) / 2)
        assert len(data["recent_jobs"]) == 2
        assert data["recent_jobs"][0]["repo_name"] == "other-repo"  # Most recent first

def test_webhook_updates_history():
    """Test that webhook CI endpoint updates history."""
    payload = {
        "repo_name": "dcsp-repo",
        "branch": "feat-1",
        "ci_job_name": "build-and-test",
        "log_content": "Traceback (most recent call last):\n  File \"test.py\", line 1, in <module>\n    raise ValueError(\"error\")"
    }

    # Mock the pipeline components
    # We patch at the module where they are used (src.pipeline or src.api.webhook)
    # src.api.webhook imports parse_log from src.dfle.log_parser
    # src.pipeline imports parse_log from src.dfle.log_parser
    
    # We need to mock parse_log to return a ParsedLog object
    from src.dfle.log_parser import ParsedLog
    
    with patch("src.api.webhook.REPO_MANAGER.clone_or_pull", return_value="/tmp/fake-repo"), \
         patch("src.api.webhook.GLOBAL_INDEXER.index_repository", return_value=None), \
         patch("src.pipeline.parse_log", return_value=ParsedLog(raw_content="logs", stack_traces=[])), \
         patch("src.slm.bedrock_client.BedrockClient.generate_patch", return_value="Fixed it"), \
         patch("src.pipeline.localize", return_value=[]), \
         patch("src.pipeline.match") as mock_match, \
         patch("src.pipeline.GLOBAL_REPAIR_MEMORY.lookup", return_value=None), \
         patch("src.api.webhook.GLOBAL_SECRET_MANAGER.get_webhook_secret", return_value=""):

        # Make match return no match
        mock_match.return_value.matched = False

        response = client.post("/webhook/ci", json=payload)

    assert response.status_code == 200
    assert len(JOB_HISTORY) >= 1
    # We check if *a* job was added. Since we mocked localize returning [], 
    # run_repair might fail or return a result with success=False.
    # The webhook just adds whatever run_repair returns.

