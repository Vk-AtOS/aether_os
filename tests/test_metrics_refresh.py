"""KAN-50: the scrape-time gauges."""
import asyncio
from datetime import datetime
from unittest.mock import patch

from sqlalchemy.dialects import sqlite

from aether_os.core.resilience import get_breaker, reset_all
from aether_os.core.telemetry import metrics


def test_backlog_query_is_valid_and_only_counts_open_requests():
    sql = str(metrics.backlog_statement(datetime(2026, 1, 1)).compile(dialect=sqlite.dialect()))
    assert "prime_requests" in sql and "status" in sql and "expires_at" in sql and "min(" in sql.lower()


def test_refresh_sets_breaker_approval_and_readiness_gauges():
    reset_all()
    b = get_breaker("velaris", failure_threshold=1)
    b.record_failure("x")
    snap = {"ready": True, "degraded": ["velaris"], "components": {"velaris": {"status": "degraded"}, "postgres": {"status": "ok"}}}

    async def fake_snapshot():
        return snap

    with patch.object(metrics, "snapshot", fake_snapshot), \
            patch.object(metrics, "dlq_depth", return_value=2):
        asyncio.run(metrics.refresh(approvals=(3, 5400.0)))
    v = lambda g, **l: (g.labels(**l) if l else g)._value.get()  # noqa: E731
    assert v(metrics.BREAKER_OPEN, name="velaris") == 1
    assert v(metrics.COMPONENT_DEGRADED, component="velaris") == 1 and v(metrics.COMPONENT_DEGRADED, component="postgres") == 0
    assert v(metrics.READY) == 1 and v(metrics.QUEUE_DLQ_DEPTH) == 2
    assert v(metrics.APPROVALS_PENDING) == 3 and v(metrics.APPROVAL_OLDEST_AGE) == 5400.0
    reset_all()
