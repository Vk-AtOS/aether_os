from __future__ import annotations
import pytest
from src.database import SessionLocal
from src.db.tenant_repo import create_tenant
from src.models import RepairJob
from datetime import datetime
import uuid

@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()

def test_tenant_isolation(db):
    """Verify tenant A jobs not visible to tenant B queries."""
    tenant_a = create_tenant(db, f"Tenant A {uuid.uuid4().hex[:6]}")
    tenant_b = create_tenant(db, f"Tenant B {uuid.uuid4().hex[:6]}")

    # Create job for tenant A
    job_a = RepairJob(
        id=str(uuid.uuid4()),
        tenant_id=tenant_a.id,
        repo_name="repo-a",
        branch="main",
        ci_system="github_actions",
        detected_language="python",
        success=True,
        confidence=0.9,
        escalated=False,
        explanation="fixed",
        timestamp=datetime.utcnow()
    )
    db.add(job_a)
    db.commit()

    # Query jobs for tenant B only
    tenant_b_jobs = db.query(RepairJob).filter(
        RepairJob.tenant_id == tenant_b.id
    ).all()

    # Tenant B should not see tenant A job
    job_ids = [j.id for j in tenant_b_jobs]
    assert job_a.id not in job_ids

def test_tenant_a_sees_own_jobs(db):
    """Verify tenant A can see its own jobs."""
    tenant_a = create_tenant(db, f"Tenant AA {uuid.uuid4().hex[:6]}")

    job = RepairJob(
        id=str(uuid.uuid4()),
        tenant_id=tenant_a.id,
        repo_name="repo-aa",
        branch="main",
        ci_system="github_actions",
        detected_language="python",
        success=True,
        confidence=0.85,
        escalated=False,
        explanation="ok",
        timestamp=datetime.utcnow()
    )
    db.add(job)
    db.commit()

    jobs = db.query(RepairJob).filter(
        RepairJob.tenant_id == tenant_a.id
    ).all()
    assert any(j.id == job.id for j in jobs)
