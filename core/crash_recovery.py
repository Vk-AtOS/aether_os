"""Startup crash recovery: mark runs whose worker died as 'interrupted'.

Several workers share one database and each runs this at startup, so "status = running"
alone is not proof of a crash: it is usually a sibling worker's live run. A run is only
orphaned if nothing has touched it (no event, no phase update) for STALE seconds.
"""
from __future__ import annotations

import os
import time

from sqlalchemy import text

STALE_SECONDS = float(os.environ.get("CRASH_RECOVERY_STALE_SECONDS", "900"))


async def mark_orphaned_runs(session, now: float | None = None, stale: float | None = None) -> tuple[int, int]:
    """Returns (phases, runs) marked interrupted. Caller commits."""
    now = time.time() if now is None else now
    cutoff = now - (STALE_SECONDS if stale is None else stale)
    runs = await session.execute(
        text(
            "UPDATE runs SET status='interrupted', finished_at=:ts "
            "WHERE status='running' AND COALESCE(started_at, 0) < :cut "
            "AND NOT EXISTS (SELECT 1 FROM events e WHERE e.run_id = runs.id AND e.timestamp >= :cut) "
            "AND NOT EXISTS (SELECT 1 FROM phase_completions p WHERE p.run_id = runs.id AND p.updated_at >= :cut)"
        ),
        {"ts": now, "cut": cutoff},
    )
    phases = await session.execute(
        text(
            "UPDATE phase_completions SET status='interrupted', updated_at=:ts "
            "WHERE status='running' AND run_id IN (SELECT id FROM runs WHERE status='interrupted')"
        ),
        {"ts": now},
    )
    return phases.rowcount, runs.rowcount
