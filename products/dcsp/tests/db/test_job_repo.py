"""
Tests for RepairJob database repository.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.models import Base
from src.db.job_repo import save_job, get_recent_jobs, update_job_approval, get_job_stats

# Use in-memory SQLite for repository tests
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture
def db_session():
    """Create all tables and provide a session for each test."""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

def test_save_and_retrieve_job(db_session):
    """Test saving a job and retrieving it."""
    job_data = {
        "repo_name": "acme/test",
        "branch": "main",
        "success": True,
        "confidence": 0.95,
        "explanation": "Fixed everything",
        "violations": ["v1", "v2"]
    }
    saved = save_job(db_session, job_data)
    assert saved.id is not None
    assert saved.repo_name == "acme/test"
    assert saved.success is True
    assert saved.confidence == 0.95
    assert "v1" in saved.violations

def test_get_recent_jobs_ordering(db_session):
    """Test that recent jobs are ordered by timestamp desc."""
    from datetime import datetime, timedelta
    
    # Save two jobs with different timestamps
    save_job(db_session, {"repo_name": "old", "branch": "b", "explanation": "e", "timestamp": (datetime.utcnow() - timedelta(hours=1)).isoformat()})
    save_job(db_session, {"repo_name": "new", "branch": "b", "explanation": "e", "timestamp": datetime.utcnow().isoformat()})
    
    recent = get_recent_jobs(db_session)
    assert len(recent) == 2
    assert recent[0].repo_name == "new"
    assert recent[1].repo_name == "old"

def test_update_job_approval(db_session):
    """Test updating approval status."""
    job = save_job(db_session, {"repo_name": "test", "branch": "b", "explanation": "e"})
    assert job.approved is None
    
    success = update_job_approval(db_session, job.id, True)
    assert success is True
    assert job.approved is True

def test_get_job_stats_empty(db_session):
    """Test stats on empty DB."""
    stats = get_job_stats(db_session)
    assert stats["total"] == 0
    assert stats["avg_confidence"] == 0.0

def test_get_job_stats_with_data(db_session):
    """Test stats with mixed data."""
    save_job(db_session, {"repo_name": "r1", "branch": "b", "success": True, "confidence": 0.8, "explanation": "e"})
    save_job(db_session, {"repo_name": "r2", "branch": "b", "success": False, "escalated": True, "confidence": 0.4, "explanation": "e"})
    
    stats = get_job_stats(db_session)
    assert stats["total"] == 2
    assert stats["successful"] == 1
    assert stats["escalated"] == 1
    assert stats["avg_confidence"] == pytest.approx(0.6)
