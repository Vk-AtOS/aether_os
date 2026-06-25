"""
Federation registry server tests.

Patterns are now persisted in PostgreSQL, not an in-memory dict.
These tests use a live SQLite DB (via DATABASE_URL fallback) so they
remain runnable without a Postgres service.
"""

from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from src.federation.registry_server import registry_app

client = TestClient(registry_app)


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "patterns" in data


def test_submit_pattern():
    r = client.post("/api/patterns", json={
        "fingerprint": "fp_test_001_unique",
        "error_type": "AttributeError",
        "language": "python",
        "patch_template": "+x = x or {}",
        "log_snippet": "AttributeError fixed"
    })
    assert r.status_code == 201
    data = r.json()
    assert "id" in data


def test_get_pattern_not_found():
    r = client.get("/api/patterns/nonexistent_id_xyz")
    assert r.status_code == 404


def test_list_patterns():
    r = client.get("/api/patterns")
    assert r.status_code == 200
    data = r.json()
    assert "patterns" in data
    assert "total" in data


def test_registry_stats():
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total_patterns" in data
    assert "languages" in data
