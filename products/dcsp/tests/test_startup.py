from fastapi.testclient import TestClient
from src.api.main import app
import os

client = TestClient(app)

def test_health_endpoint_has_database_field():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "database" in data
    assert data["database"] in ["connected", "disconnected"]

def test_health_endpoint_has_notifications_field():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "notifications" in data
    assert "slack_configured" in data["notifications"]

def test_health_endpoint_structure():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "environment" in data
    assert "database" in data
    assert "bedrock" in data
    assert "notifications" in data
