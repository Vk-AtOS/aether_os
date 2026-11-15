#!/usr/bin/env python3.11
"""Delete old rows of the append-only tables that grow without bound (run it daily from cron / a Kubernetes CronJob).

    python3.11 scripts/retention_purge.py [--dry-run]

Windows (days) come from the environment; the defaults are an engineering choice, the legal retention period is the
owner's decision (KAN-204): AETHER_RETENTION_TRACE_DAYS=30 (llm_traces: full prompts and responses),
AETHER_RETENTION_EVENT_DAYS=180 (pipeline_events, events), AETHER_RETENTION_SNAPSHOT_DAYS=90 (snapshots: file contents).
0 disables a window. Rows go in batches so that no long lock is held.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aether_os.core.db import _build_db_url  # noqa: E402

logger = logging.getLogger("retention_purge")
BATCH = 5000

# table, timestamp column, kind of timestamp, env var, default days
POLICY = (
    ("llm_traces", "created_at", "datetime", "AETHER_RETENTION_TRACE_DAYS", 30),
    ("pipeline_events", "created_at", "datetime", "AETHER_RETENTION_EVENT_DAYS", 180),
    ("events", "timestamp", "epoch", "AETHER_RETENTION_EVENT_DAYS", 180),
    ("snapshots", "created_at", "epoch", "AETHER_RETENTION_SNAPSHOT_DAYS", 90),
)


def purge(engine, now: datetime | None = None, dry_run: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    deleted: dict = {}
    for table, col, kind, env, default in POLICY:
        days = int(os.environ.get(env, default))
        if days <= 0:
            continue
        cutoff_dt = now - timedelta(days=days)
        cutoff = cutoff_dt.replace(tzinfo=None) if kind == "datetime" else cutoff_dt.timestamp()
        total = 0
        with engine.begin() as conn:
            if dry_run:
                total = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {col} < :c"), {"c": cutoff}).scalar() or 0
        while not dry_run:
            with engine.begin() as conn:
                n = conn.execute(
                    text(f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} WHERE {col} < :c LIMIT {BATCH})"),
                    {"c": cutoff},
                ).rowcount
            total += n
            if n < BATCH:
                break
            time.sleep(0.05)
        deleted[table] = total
        logger.info("retention: %s %s rows older than %d days", table, "would delete" if dry_run else "deleted", days)
    return deleted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    url = _build_db_url().replace("+aiosqlite", "").replace("+asyncpg", "")
    print(purge(create_engine(url), dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
