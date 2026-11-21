"""Operational metrics beyond HTTP rate/latency (those come from the instrumentator): queue depth, model cost, approval
backlog, breaker and bulkhead state (KAN-50). The names here are the ones deploy/observability/alerts.yml uses;
tests/test_alert_rules.py checks that every metric an alert references is defined in code.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from prometheus_client import Counter, Gauge
from sqlalchemy import func, select

from aether_os.core.db import get_session_factory
from aether_os.core.queue.sqs_client import dlq_depth
from aether_os.core.resilience import all_breakers, all_bulkheads
from aether_os.core.resilience.health import snapshot
from aether_os.core.telemetry.events import GUARDIAN_TAMPER, LLM_REFUSED, SANDBOX_START_FAILURES  # noqa: F401  (re-exported)
from aether_os.prime.models import PrimeRequest

logger = logging.getLogger(__name__)

LLM_COST = Counter("aether_llm_cost_usd_total", "Estimated model spend", ["model"])
BUDGET_ALERTS = Counter("aether_budget_alert_total", "Organisations that crossed 80% of their monthly model budget (once each per month)")
LLM_TOKENS = Counter("aether_llm_tokens_total", "Model tokens", ["direction"])
BREAKER_OPEN = Gauge("aether_breaker_open", "1 while a circuit breaker is open or half-open", ["name"])
BULKHEAD_IN_USE = Gauge("aether_bulkhead_in_use", "Calls in flight in a bulkhead", ["name"])
BULKHEAD_REJECTED = Gauge("aether_bulkhead_rejected_total", "Calls refused by a full bulkhead", ["name"])
QUEUE_DLQ_DEPTH = Gauge("aether_queue_dead_letters", "Dead-lettered pipeline jobs (-1 = unknown)")
APPROVALS_PENDING = Gauge("aether_approvals_pending", "Prime approval requests waiting for a decision")
APPROVAL_OLDEST_AGE = Gauge("aether_approval_oldest_pending_seconds", "Age of the oldest pending approval request")
READY = Gauge("aether_ready", "1 when /readyz would answer 200")
BACKUP_AGE = Gauge("aether_backup_age_seconds", "Age of the newest database dump in BACKUP_DIR (not set when the directory is not visible)")
COMPONENT_DEGRADED = Gauge("aether_component_degraded", "1 while a component is degraded or down", ["component"])


def newest_backup_age(backup_dir: str) -> Optional[float]:
    """Seconds since the newest aetheros_* dump was written; None when the directory does not exist (a backup that
    cannot be seen is not reported as fresh or stale); inf when it exists but holds no dump."""
    d = Path(backup_dir)
    if not d.is_dir():
        return None
    mtimes = [f.stat().st_mtime for f in d.glob("aetheros_*")]
    return max(time.time() - max(mtimes), 0.0) if mtimes else float("inf")


def observe_cost(model: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
    LLM_COST.labels(model=model or "unknown").inc(max(cost_usd, 0.0))
    LLM_TOKENS.labels(direction="input").inc(max(input_tokens, 0))
    LLM_TOKENS.labels(direction="output").inc(max(output_tokens, 0))


def backlog_statement(now: datetime):
    """Pending (not yet expired) approval requests: how many, and when the oldest was created."""
    return (select(func.count(), func.min(PrimeRequest.created_at))
            .where(PrimeRequest.status == "pending", PrimeRequest.expires_at > now))


async def _approval_backlog() -> tuple[int, float]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)   # the columns hold naive UTC (core.models._utcnow)
    async with get_session_factory()() as s:
        row = (await s.execute(backlog_statement(now))).one()
    count, oldest = int(row[0]), row[1]
    if oldest is None:
        return count, 0.0
    return count, max((now - oldest).total_seconds(), 0.0)


async def refresh(approvals: Optional[tuple[int, float]] = None) -> None:
    """Bring the gauges up to date just before a scrape. Every source is best effort: a failing one is logged and its
    gauge keeps its last value, so a broken probe cannot break the scrape (and shows as a stale value, not a lie)."""
    for name, b in all_breakers().items():
        BREAKER_OPEN.labels(name=name).set(0 if b.state == "closed" else 1)
    for name, bh in all_bulkheads().items():
        BULKHEAD_IN_USE.labels(name=name).set(bh.in_use)
        BULKHEAD_REJECTED.labels(name=name).set(bh.rejected_total)
    try:
        snap = await snapshot()
        READY.set(1 if snap["ready"] else 0)
        for comp, info in snap["components"].items():
            COMPONENT_DEGRADED.labels(component=comp).set(0 if info["status"] == "ok" else 1)
    except Exception as e:
        logger.warning("metrics: health snapshot failed: %s", type(e).__name__)
    try:
        QUEUE_DLQ_DEPTH.set(await asyncio.to_thread(dlq_depth))
    except Exception as e:
        logger.warning("metrics: dlq depth failed: %s", type(e).__name__)
    try:
        count, age = approvals if approvals is not None else await _approval_backlog()
        APPROVALS_PENDING.set(count)
        APPROVAL_OLDEST_AGE.set(age)
    except Exception as e:
        logger.warning("metrics: approval backlog failed: %s", type(e).__name__)
    try:
        age = await asyncio.to_thread(newest_backup_age, os.environ.get("BACKUP_DIR", "/var/backups/aetheros"))
        if age is not None:
            BACKUP_AGE.set(age)
    except Exception as e:
        logger.warning("metrics: backup age failed: %s", type(e).__name__)
