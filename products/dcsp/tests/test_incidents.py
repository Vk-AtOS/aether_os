from __future__ import annotations
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.models import Base
from src.db.incident_repo import (
    get_or_create_incident,
    get_incident_by_id,
    list_incidents,
    resolve_incident,
    escalate_incident,
    get_incident_stats
)

# In-memory SQLite for tests
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False}
)
TestSession = sessionmaker(bind=engine)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)

@pytest.fixture
def db():
    session = TestSession()
    yield session
    session.close()

def test_create_incident(db):
    incident = get_or_create_incident(
        db,
        fingerprint="AttributeError:NoneType",
        error_type="AttributeError",
        language="python",
        repo_name="acme/billing"
    )
    assert incident.id is not None
    assert incident.job_count == 1
    assert incident.status == "active"

def test_get_or_create_deduplicates(db):
    """Same fingerprint → same incident."""
    i1 = get_or_create_incident(
        db, "fp_dedup", "TypeError",
        "python", "acme/api")
    i2 = get_or_create_incident(
        db, "fp_dedup", "TypeError",
        "python", "acme/api")
    assert i1.id == i2.id
    assert i2.job_count == 2

def test_incident_adds_new_repos(db):
    """New repo added to affected_repos."""
    i1 = get_or_create_incident(
        db, "fp_repos", "ImportError",
        "python", "acme/svc-a")
    i2 = get_or_create_incident(
        db, "fp_repos", "ImportError",
        "python", "acme/svc-b")
    import json
    repos = json.loads(i2.affected_repos)
    assert "acme/svc-a" in repos
    assert "acme/svc-b" in repos

def test_get_incident_by_id(db):
    incident = get_or_create_incident(
        db, "fp_byid", "ValueError",
        "python", "repo/x")
    found = get_incident_by_id(
        db, incident.id)
    assert found is not None
    assert found.id == incident.id

def test_get_incident_not_found(db):
    found = get_incident_by_id(
        db, "nonexistent_id")
    assert found is None

def test_list_incidents(db):
    get_or_create_incident(
        db, "fp_list1", "TypeError",
        "python", "r/a")
    get_or_create_incident(
        db, "fp_list2", "ImportError",
        "python", "r/b")
    incidents = list_incidents(db)
    assert len(incidents) == 2

def test_list_incidents_filter_status(db):
    i = get_or_create_incident(
        db, "fp_status", "TypeError",
        "python", "r/a")
    resolve_incident(
        db, i.id, "Fixed")
    active = list_incidents(
        db, status="active")
    resolved = list_incidents(
        db, status="resolved")
    assert len(active) == 0
    assert len(resolved) == 1

def test_resolve_incident(db):
    incident = get_or_create_incident(
        db, "fp_resolve", "KeyError",
        "python", "r/a")
    resolved = resolve_incident(
        db, incident.id, "Root cause fixed")
    assert resolved.status == "resolved"
    assert resolved.resolution == \
        "Root cause fixed"

def test_escalate_incident(db):
    incident = get_or_create_incident(
        db, "fp_escalate", "RuntimeError",
        "python", "r/a")
    escalated = escalate_incident(
        db, incident.id)
    assert escalated.status == "escalated"

def test_resolve_nonexistent(db):
    result = resolve_incident(
        db, "fake_id", "resolution")
    assert result is None

def test_incident_stats(db):
    get_or_create_incident(
        db, "fp_s1", "TypeError",
        "python", "r/a")
    i2 = get_or_create_incident(
        db, "fp_s2", "ImportError",
        "python", "r/b")
    escalate_incident(db, i2.id)
    stats = get_incident_stats(db)
    assert stats["total"] == 2
    assert stats["active"] == 1
    assert stats["escalated"] == 1
    assert stats["resolved"] == 0

def test_incident_api_list():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "incident_list_token"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/api/incidents",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    assert "incidents" in r.json()

def test_incident_api_stats():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "incident_stats_token"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/api/incidents/stats",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
