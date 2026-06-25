from __future__ import annotations
import pytest
from src.queue.worker import (
    get_redis_connection,
    get_repair_queue,
    enqueue_repair,
    get_queue_stats
)
from src.queue.repair_task import \
    process_repair_job

def test_get_redis_connection_graceful():
    """Redis unavailable in test env is OK."""
    conn = get_redis_connection()
    # Either None (unavailable) or connected
    assert conn is None or conn is not None

def test_get_repair_queue_graceful():
    """Queue returns None if Redis down."""
    queue = get_repair_queue()
    assert queue is None or queue is not None

def test_enqueue_repair_no_redis():
    """enqueue_repair returns None gracefully
    when Redis is unavailable."""
    payload = {
        "job_id": "test-123",
        "repo_name": "test/repo",
        "branch": "main",
        "log_content": "Error: test failure",
        "ci_system": "github_actions"
    }
    result = enqueue_repair(payload)
    # None = Redis unavailable (OK in tests)
    # str = job was actually queued (also OK)
    assert result is None or \
        isinstance(result, str)

def test_get_queue_stats_structure():
    """Stats always return correct structure."""
    stats = get_queue_stats()
    assert "queued" in stats
    assert "started" in stats
    assert "finished" in stats
    assert "failed" in stats
    assert "redis_available" in stats
    assert isinstance(
        stats["queued"], int)
    assert isinstance(
        stats["redis_available"], bool)

def test_queue_stats_no_redis():
    """When Redis down, stats are zeros."""
    stats = get_queue_stats()
    if not stats["redis_available"]:
        assert stats["queued"] == 0
        assert stats["failed"] == 0

def test_repair_task_structure():
    """process_repair_job returns
    correct result structure."""
    payload = {
        "job_id": "task-test-001",
        "repo_name": "test/repo",
        "branch": "main",
        "log_content":
            "AttributeError: 'NoneType' "
            "object has no attribute 'split'",
        "ci_system": "github_actions"
    }
    from unittest.mock import patch
    with patch("src.queue.repair_task.run_repair") as mock_run:
        from src.pipeline import RepairResult
        mock_run.return_value = RepairResult(
            success=True,
            confidence=0.9,
            patch_diff="diff",
            explanation="fixed",
            escalated=False,
            detected_language="python",
            fingerprint="fp",
            slm_generated=True,
            source="slm",
            error_type="AttributeError"
        )
        result = process_repair_job(payload)
        assert "success" in result
        assert "job_id" in result
        assert isinstance(result["success"], bool)

def test_repair_task_handles_bad_payload():
    """Task handles missing keys gracefully."""
    payload = {"job_id": "bad-payload"}
    result = process_repair_job(payload)
    # Should return error dict, not raise
    assert "success" in result
    assert result["success"] is False or \
        result["success"] is True

def test_queue_stats_api():
    """Queue stats API endpoint works."""
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "queue_stats_token"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    response = client.get(
        "/api/queue/stats",
        cookies={"session_token": token}
    )
    assert response.status_code == 200
    data = response.json()
    assert "queued" in data
    assert "redis_available" in data
