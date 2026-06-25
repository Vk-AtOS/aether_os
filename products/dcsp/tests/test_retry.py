from __future__ import annotations
import pytest
from src.queue.retry_manager import (
    should_retry,
    get_retry_delay,
    record_retry_attempt,
    send_to_dead_letter_queue,
    process_with_retry,
    MAX_RETRIES,
    RETRY_DELAYS
)
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

def test_should_retry_under_limit():
    assert should_retry("job-1", 0) is True
    assert should_retry("job-1", 1) is True
    assert should_retry("job-1", 2) is True

def test_should_not_retry_at_limit():
    assert should_retry(
        "job-1", MAX_RETRIES) is False

def test_retry_delays_increasing():
    d0 = get_retry_delay(0)
    d1 = get_retry_delay(1)
    d2 = get_retry_delay(2)
    assert d0 < d1 < d2

def test_retry_delay_beyond_list():
    """Beyond list length returns last value."""
    last = get_retry_delay(100)
    assert last == RETRY_DELAYS[-1]

def test_record_retry_attempt_no_error():
    """record_retry_attempt logs without raising."""
    record_retry_attempt(
        "job-test", 1, "connection timeout")

def test_send_to_dlq_unknown_job():
    """DLQ handles job not in DB gracefully."""
    payload = {
        "job_id": f"dlq-{uuid.uuid4().hex[:8]}",
        "repo_name": "test/repo",
        "branch": "main"
    }
    entry = send_to_dead_letter_queue(
        payload, "Pipeline crashed", 3)
    assert entry["status"] == "dead_letter"
    assert entry["attempts"] == 3
    assert "error" in entry
    assert "timestamp" in entry

def test_send_to_dlq_existing_job(db):
    """DLQ marks existing job as escalated."""
    tenant = create_tenant(
        db, f"DLQ Tenant {uuid.uuid4().hex[:6]}")
    job_id = str(uuid.uuid4())
    job = RepairJob(
        id=job_id,
        tenant_id=tenant.id,
        repo_name="test/repo",
        branch="main",
        ci_system="github_actions",
        detected_language="python",
        success=False,
        confidence=0.0,
        escalated=False,
        explanation="initial",
        timestamp=datetime.utcnow()
    )
    db.add(job)
    db.commit()

    send_to_dead_letter_queue(
        {"job_id": job_id},
        "Permanent failure", 3)

    db.refresh(job)
    assert job.escalated is True
    assert "DLQ" in job.explanation

def test_process_with_retry_success():
    """Successful processor returns
    success on first attempt."""
    def mock_processor(payload):
        return {"success": True,
                "job_id": payload["job_id"]}

    result = process_with_retry(
        {"job_id": "retry-ok-001",
         "repo_name": "r",
         "branch": "main",
         "log_content": "err"},
        processor_fn=mock_processor
    )
    assert result["status"] == "success"
    assert result["attempts"] == 1

def test_process_with_retry_exhausted():
    """All retries fail, goes to DLQ."""
    call_count = [0]
    def always_fails(payload):
        call_count[0] += 1
        return {"success": False,
                "error": "always fails"}

    result = process_with_retry(
        {"job_id": f"retry-fail-"
                   f"{uuid.uuid4().hex[:6]}",
         "repo_name": "r",
         "branch": "main",
         "log_content": "err"},
        processor_fn=always_fails
    )
    assert result["status"] == "dead_letter"
    assert result["attempts"] == MAX_RETRIES
    assert call_count[0] == MAX_RETRIES

def test_process_with_retry_second_attempt():
    """Fails first, succeeds second."""
    calls = [0]
    def fails_once(payload):
        calls[0] += 1
        if calls[0] == 1:
            return {"success": False,
                    "error": "first fail"}
        return {"success": True,
                "job_id": payload["job_id"]}

    result = process_with_retry(
        {"job_id": "retry-second-001",
         "repo_name": "r",
         "branch": "main",
         "log_content": "err"},
        processor_fn=fails_once
    )
    assert result["status"] == "success"
    assert result["attempts"] == 2
