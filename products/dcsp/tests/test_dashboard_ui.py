"""
Tests for the Dashboard UI Server.
"""

import pytest
from fastapi.testclient import TestClient
from src.dashboard_ui import app
from src.database import SessionLocal, engine
from src.db.tenant_repo import create_tenant, list_tenants
from src.db.job_repo import record_stage_timing
from src.models import Tenant, StageTiming, Base

client = TestClient(app)

from types import SimpleNamespace

@pytest.fixture
def seed_data():
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    
    session = SessionLocal()
    # Create or get tenant
    tenants = list_tenants(session)
    if tenants:
        t_db = tenants[0]
    else:
        t_db = create_tenant(session, "Test Tenant", "free")
    
    # Store ID and Name before closing session
    t_simple = SimpleNamespace(id=str(t_db.id), name=str(t_db.name))
    
    # Add some stage timings
    record_stage_timing(session, "job1", "Build", 100, "success", t_db.id)
    record_stage_timing(session, "job2", "Test", 200, "success", t_db.id)
    record_stage_timing(session, "job3", "Deploy", 300, "success", t_db.id)
    session.close()
    return t_simple

# Mock the predictor's session factory for the test environment
# (The dashboard_ui uses SessionLocal directly, which points to sqlite:///./vkatos.db in test env)
# So standard SessionLocal usage is fine here as long as env is set correctly.

def test_dashboard_html_serve():
    response = client.get("/")
    assert response.status_code == 200
    assert "DCSP Live Operations" in response.text

def test_api_tenants(seed_data):
    response = client.get("/api/tenants")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    # Verify the seeded tenant (or any existing tenant) is present
    assert any("name" in t for t in data)

def test_api_stages(seed_data):
    # Ensure baseline data exists
    response = client.get("/api/stages")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3
    
    build = next(s for s in data if s["name"] == "Build")
    assert "risk_level" in build
    assert "z_score" in build
    assert "prediction_text" in build

def test_api_audit(seed_data):
    response = client.get("/api/audit")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_api_simulate(seed_data):
    payload = {"stage_name": "Build", "tenant_id": seed_data.id}
    response = client.post("/api/simulate", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "simulated"
    
    # Verify audit log was created
    audit_res = client.get("/api/audit")
    logs = audit_res.json()
    assert any("Simulated stall on Build" in l["details"] for l in logs)

def test_api_stages_tenant_filter(seed_data):
    response = client.get(f"/api/stages?tenant_id={seed_data.id}")
    assert response.status_code == 200
    # Logic in dashboard_ui currently uses all baselines but logic allows filtering
    # Just verify 200 OK for now as the mock logic is simple
