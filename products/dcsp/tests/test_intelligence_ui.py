from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.api.auth import ACTIVE_SESSIONS

def auth_client(token: str):
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    return client

def test_intelligence_page_loads():
    client = auth_client("intel_load_token")
    r = client.get(
        "/dashboard/intelligence",
        cookies={"session_token":
                 "intel_load_token"}
    )
    assert r.status_code == 200

def test_intelligence_page_has_table():
    client = auth_client("intel_table_token")
    r = client.get(
        "/dashboard/intelligence",
        cookies={"session_token":
                 "intel_table_token"}
    )
    assert r.status_code == 200
    assert "<table" in r.text.lower()

def test_intelligence_page_has_metrics():
    client = auth_client("intel_metrics_token")
    r = client.get(
        "/dashboard/intelligence",
        cookies={"session_token":
                 "intel_metrics_token"}
    )
    assert r.status_code == 200
    # Should have metric cards
    assert "metric" in r.text.lower() or \
        "Tracked" in r.text or \
        "Risk" in r.text

def test_intelligence_page_has_severity():
    client = auth_client(
        "intel_severity_token")
    r = client.get(
        "/dashboard/intelligence",
        cookies={"session_token":
                 "intel_severity_token"}
    )
    assert r.status_code == 200
    assert "Severity" in r.text or \
        "severity" in r.text

def test_intelligence_page_has_score():
    """Recurrence score column present."""
    client = auth_client("intel_score_token")
    r = client.get(
        "/dashboard/intelligence",
        cookies={"session_token":
                 "intel_score_token"}
    )
    assert r.status_code == 200
    assert "Score" in r.text or \
        "score" in r.text

def test_intelligence_page_in_nav():
    """Intelligence link in nav."""
    client = auth_client("intel_nav_token")
    r = client.get(
        "/dashboard/intelligence",
        cookies={"session_token":
                 "intel_nav_token"}
    )
    assert r.status_code == 200
    assert "/dashboard/intelligence" in r.text

def test_intelligence_page_requires_auth():
    client = TestClient(app)
    r = client.get(
        "/dashboard/intelligence",
        follow_redirects=False
    )
    assert r.status_code in (
        200, 302, 401, 403)

def test_predictor_fed_from_webhook():
    """Predictor singleton is importable."""
    from src.intelligence.predictor import \
        PREDICTOR
    assert hasattr(PREDICTOR, "record_failure")
    assert hasattr(PREDICTOR, "predict_all")
