"""Audit chain under concurrent appends: every append links, and a failed link is visible.

Real chain code on a throwaway SQLite file, and on a throwaway PostgreSQL
schema (created and dropped here; the dev tables are never written) so the advisory-lock
path is exercised too.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import aether_os.core.db as db
from aether_os.core.audit import chain, ledger as ledger_mod
from aether_os.core.audit.chain import AuditChainEntry
from aether_os.core.audit.ledger import DecisionLedger
from aether_os.core.models import AuditLog

pytestmark = pytest.mark.asyncio
N = 40


async def _use_database(monkeypatch, url: str):
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(
            c, tables=[AuditChainEntry.__table__, AuditLog.__table__]))
    return engine


@pytest_asyncio.fixture
async def sqlite_db(tmp_path, monkeypatch):
    engine = await _use_database(monkeypatch, f"sqlite+aiosqlite:///{tmp_path}/chain.db")
    yield db.get_session_factory()
    await engine.dispose()


def _local_postgres_url() -> str:
    url = os.environ.get("AETHER_PG_TEST_URL", "")
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not url and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip("'\"")
    return url if url.startswith("postgres") else ""


@pytest_asyncio.fixture
async def postgres_db(monkeypatch):
    """The chain tables in a throwaway schema of the local PostgreSQL database."""
    base = _local_postgres_url()
    if not base:
        pytest.skip("no local PostgreSQL URL (AETHER_PG_TEST_URL or .env DATABASE_URL)")
    schema = f"chain_test_{uuid.uuid4().hex[:10]}"
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
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: db.Base.metadata.create_all(
                c, tables=[AuditChainEntry.__table__, AuditLog.__table__]))
        yield db.get_session_factory()
    finally:
        await engine.dispose()
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def _assert_all_linked(n: int) -> None:
    result = await chain.verify()
    assert result.ok, result.reason
    assert result.entries_checked == n
    assert [e["seq"] for e in await chain.read_entries(limit=n + 5)] == list(range(1, n + 1))


async def test_concurrent_appends_all_link_sqlite(sqlite_db):
    await asyncio.gather(*(chain.append(f"user-{i}", "thing.done", {"i": i}) for i in range(N)))
    await _assert_all_linked(N)


async def test_concurrent_appends_all_link_postgres(postgres_db):
    await asyncio.gather(*(chain.append(f"user-{i}", "thing.done", {"i": i}) for i in range(N)))
    await _assert_all_linked(N)


async def test_postgres_advisory_lock_alone_serialises_writers(postgres_db, monkeypatch):
    """Writers in different processes do not share the in-process lock. Give every
    append its own lock (as separate processes would have) and the advisory lock
    alone must still make all of them link — with no retries to hide a race."""
    monkeypatch.setattr(chain, "_local_lock", asyncio.Lock)
    monkeypatch.setattr(chain, "_APPEND_ATTEMPTS", 1)
    await asyncio.gather(*(chain.append(f"user-{i}", "thing.done", {"i": i}) for i in range(N)))
    await _assert_all_linked(N)


async def _audit_events_all_carry_a_chain_link(sf) -> None:
    before = ledger_mod.unlinked_audit_event_count()
    ledger = DecisionLedger()
    await asyncio.gather(*(
        ledger.async_log_audit_event("org-1", f"user-{i}", "login", "session", f"s-{i}")
        for i in range(N)))
    await _assert_all_linked(N)
    async with sf() as s:
        linked = (await s.execute(select(AuditLog.prev_hash))).scalars().all()
    assert len(linked) == N and None not in linked
    assert sorted(linked) == sorted(e["entry_hash"] for e in await chain.read_entries(limit=N))
    assert ledger_mod.unlinked_audit_event_count() == before


async def test_concurrent_audit_events_all_carry_a_chain_link_sqlite(sqlite_db):
    await _audit_events_all_carry_a_chain_link(sqlite_db)


async def test_concurrent_audit_events_all_carry_a_chain_link_postgres(postgres_db):
    await _audit_events_all_carry_a_chain_link(postgres_db)


async def test_failed_chain_link_is_logged_counted_and_flagged(sqlite_db, monkeypatch, caplog):
    async def _broken(**_kwargs):
        raise RuntimeError("chain storage unavailable")

    monkeypatch.setattr(chain, "append", _broken)
    before = ledger_mod.unlinked_audit_event_count()
    with caplog.at_level(logging.ERROR, logger=ledger_mod.logger.name):
        await DecisionLedger().async_log_audit_event("org-1", "user-1", "login", metadata={"k": "v"})

    assert ledger_mod.unlinked_audit_event_count() == before + 1
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and "AUDIT CHAIN LINK FAILED" in errors[0].getMessage()
    async with sqlite_db() as s:
        row = (await s.execute(select(AuditLog))).scalar_one()
    assert row.prev_hash is None
    assert json.loads(row.log_metadata) == {"k": "v", "chain_linked": False}
