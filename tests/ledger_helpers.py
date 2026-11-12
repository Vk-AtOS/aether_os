"""Shared fixtures for the per-organisation ledger tests: real chain code on a throwaway
SQLite file or a throwaway PostgreSQL schema, signing key and anchor file in tmp.
Not a test module (no test_ prefix)."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import aether_os.core.db as db
from aether_os.core.audit import chain
from aether_os.core.audit.backfill import AuditBackfill
from aether_os.core.audit.checkpoints import AuditCheckpoint
from aether_os.core.audit.subjects import AuditErasure, AuditOrgPepper, AuditSubject
from aether_os.core.models import AuditLog

TABLES = [chain.AuditChainEntry.__table__, AuditLog.__table__, AuditCheckpoint.__table__,
          AuditOrgPepper.__table__, AuditSubject.__table__, AuditErasure.__table__,
          AuditBackfill.__table__]


@pytest.fixture
def anchor_env(tmp_path, monkeypatch):
    """Signing key and anchor file in tmp, never in ~/.aether_os."""
    monkeypatch.setenv("AETHER_LEDGER_SIGNING_KEY", str(tmp_path / "keys" / "ledger.pem"))
    monkeypatch.setenv("AETHER_LEDGER_ANCHOR_FILE", str(tmp_path / "anchors.jsonl"))
    return tmp_path


@pytest_asyncio.fixture
async def ledger_sqlite(tmp_path, monkeypatch, anchor_env):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/ledger.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=TABLES))
    yield db.get_session_factory()
    await engine.dispose()


def local_postgres_url() -> str:
    url = os.environ.get("AETHER_PG_TEST_URL", "")
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not url and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip("'\"")
    return url if url.startswith("postgres") else ""


@pytest_asyncio.fixture
async def pg_schema(monkeypatch, anchor_env):
    """(async url, schema name) of a throwaway schema in the local PostgreSQL; dropped after.
    core.db is pointed at it with an empty schema (tables are the test's business)."""
    base = local_postgres_url()
    if not base:
        pytest.skip("no local PostgreSQL URL (AETHER_PG_TEST_URL or .env DATABASE_URL)")
    schema = f"ledger_test_{uuid.uuid4().hex[:10]}"
    url = make_url(base).set(drivername="postgresql+asyncpg")
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    except Exception as exc:
        await admin.dispose()
        pytest.skip(f"cannot create a throwaway PostgreSQL schema: {exc}")
    engine = create_async_engine(
        url, pool_size=20, connect_args={"server_settings": {"search_path": schema}})
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_session_factory", async_sessionmaker(engine, expire_on_commit=False))
    try:
        yield url, schema
    finally:
        await engine.dispose()
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def add_legacy_rows(sf, n: int) -> str:
    """n correctly linked rows in the frozen legacy chain (as before the migration).
    Returns the legacy tail hash."""
    prev = chain.GENESIS_HASH
    async with sf() as s:
        for i in range(1, n + 1):
            payload = chain.canonical_payload({"org_id": "org-old", "i": i,
                                               "ip_address": "10.0.0.7",
                                               "metadata": {"email": "old@x.test"}})
            h = chain.compute_entry_hash(prev, 100.0 + i, "u-old", "login", payload)
            s.add(chain.AuditChainEntry(seq=i, chain_id=chain.LEGACY_CHAIN, chain_seq=None,
                                        timestamp=100.0 + i, actor="u-old", action="login",
                                        payload=payload, prev_hash=prev, entry_hash=h))
            prev = h
        await s.commit()
    return prev
