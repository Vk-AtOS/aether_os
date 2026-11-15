#!/usr/bin/env python3.11
"""Bring the database to the schema the code expects (the one command compose, deploy.sh and Kubernetes run).

    python -m aether_os.scripts.db_migrate        (or: python3.11 scripts/db_migrate.py)

* EXISTING database (it has alembic_version or the runs table): `alembic upgrade head`.
* EMPTY database: create the schema from the models (the same path init_db uses for throwaway databases) and
  `alembic stamp head`. History is NOT replayed on an empty database: the chain was never run from nothing (the
  baseline already contains columns that later revisions add, and one branch alters `organisations` before the other
  creates it), so `alembic upgrade head` on a fresh Postgres fails; this was how a first `docker compose up` died.
Exit 0 = the database is at head.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the directory that contains the aether_os package

from aether_os.core.db import _build_db_url, init_db  # noqa: E402

logger = logging.getLogger("db_migrate")
ROOT = Path(__file__).resolve().parents[1]


def sync_url() -> str:
    return _build_db_url().replace("+aiosqlite", "").replace("+asyncpg", "")


def is_empty(url: str) -> bool:
    """True when the database has neither the Alembic bookkeeping table nor any AetherOS table."""
    engine = create_engine(url)
    try:
        names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    return not ({"alembic_version", "runs", "organisations", "users"} & names)


def migrate() -> str:
    """Returns "created" (empty database bootstrapped and stamped) or "upgraded"."""
    cfg = Config(str(ROOT / "alembic.ini"))
    if is_empty(sync_url()):
        logger.info("empty database: creating the schema from the models and stamping head")
        os.environ["AETHER_DB_CREATE_ALL"] = "1"      # init_db's create_all path (also on PostgreSQL)
        asyncio.run(init_db())
        command.stamp(cfg, "head")
        return "created"
    command.upgrade(cfg, "head")
    return "upgraded"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(migrate())
