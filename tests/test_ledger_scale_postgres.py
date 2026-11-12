"""Per-organisation chains on real local PostgreSQL, in a throwaway schema:
thousands of concurrent appends across organisations all link, appends do not slow
with chain length, the per-chain advisory lock alone serialises writers, and the
migration turns an existing global chain into the frozen legacy chain."""
from __future__ import annotations

import asyncio
import importlib.util
import time
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

import aether_os.core.db as db
from aether_os.core.audit import anchor, chain
from aether_os.tests.ledger_helpers import TABLES, anchor_env, pg_schema  # noqa: F401

pytestmark = pytest.mark.asyncio
ORGS = [f"org-{i}" for i in range(5)]
PER_ORG = 700
VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"


async def _create_tables():
    async with db.get_engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=TABLES))


async def _timed(org, n):
    start = time.perf_counter()
    for i in range(n):
        await chain.append("u", "thing", {"org_id": org, "i": i})
    return time.perf_counter() - start


async def test_thousands_of_concurrent_appends_across_orgs_all_link(pg_schema):
    await _create_tables()
    early = await _timed("probe", 100)
    await asyncio.gather(*(chain.append(f"u{i}", "thing", {"org_id": org, "i": i})
                           for i in range(PER_ORG) for org in ORGS))
    for org in ORGS:
        r = await chain.verify(org, full=True)
        assert r.ok and r.entries_checked == PER_ORG and r.head_seq == PER_ORG, r
    total = (await chain.verify()).entries_checked
    assert total == PER_ORG * len(ORGS) + 100

    # Append cost does not grow with the ledger (tail lookup is an index probe).
    late = await _timed("probe", 100)
    assert late < early * 3 + 0.5, (early, late)

    # Incremental verify after an anchor touches only the new entries.
    await anchor.anchor_chain(ORGS[0])
    await chain.append("u", "thing", {"org_id": ORGS[0]})
    r = await chain.verify(ORGS[0])
    assert r.ok and r.entries_checked == 1 and r.head_seq == PER_ORG + 1


async def test_per_chain_advisory_lock_alone_serialises_writers(pg_schema, monkeypatch):
    """Separate processes share no in-process lock: give every append its own and allow
    no retries; the per-chain advisory lock alone must keep every chain linked."""
    await _create_tables()
    monkeypatch.setattr(chain, "_local_lock", lambda _chain: asyncio.Lock())
    monkeypatch.setattr(chain, "_APPEND_ATTEMPTS", 1)
    await asyncio.gather(*(chain.append("u", "thing", {"org_id": org, "i": i})
                           for i in range(60) for org in ORGS[:3]))
    for org in ORGS[:3]:
        assert (await chain.verify(org, full=True)).entries_checked == 60


def _load(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_migration_freezes_the_old_chain_as_legacy(pg_schema):
    url, schema = pg_schema
    sync = create_engine(url.set(drivername="postgresql+psycopg2"),
                         connect_args={"options": f"-csearch_path={schema}"})
    try:
        def migrate(*names):
            with sync.begin() as conn:
                with Operations.context(MigrationContext.configure(conn)):
                    for n in names:
                        _load(n).upgrade()

        migrate("add_audit_chain_and_prime_delegations")   # the old global chain + trigger
        prev = chain.GENESIS_HASH
        with sync.begin() as conn:
            for i in range(1, 4):
                payload = chain.canonical_payload({"org_id": "org-old", "i": i})
                h = chain.compute_entry_hash(prev, float(i), "u", "a", payload)
                conn.execute(text("INSERT INTO audit_chain VALUES (:s, :t, 'u', 'a', :p, :prev, :h)"),
                             {"s": i, "t": float(i), "p": payload, "prev": prev, "h": h})
                prev = h
        migrate("per_org_ledger_chains")

        await chain.append("u", "thing", {"org_id": "org-a"})
        await chain.append("u", "thing", {"org_id": "org-b"})
        rows = await chain.read_entries()
        assert [r["chain_id"] for r in rows] == ["legacy"] * 3 + ["org-a", "org-b"]
        assert [r["seq"] for r in rows] == [1, 2, 3, 4, 5]          # sequence continues
        assert rows[3]["prev_hash"] == prev == rows[4]["prev_hash"]  # linked to the legacy tail
        assert (await chain.verify()).entries_checked == 5
        assert (await chain.verify("org-a", full=True)).ok
        assert (await anchor.anchor_chain(chain.LEGACY_CHAIN))["chain_seq"] == 3

        with sync.begin() as conn:
            for stmt in ("INSERT INTO audit_chain (chain_id, timestamp, actor, action, payload, "
                         "prev_hash, entry_hash) VALUES ('legacy', 1, 'u', 'a', '{}', 'x', 'y')",
                         "UPDATE audit_chain SET actor = 'm' WHERE seq = 1",
                         "DELETE FROM audit_chain WHERE seq = 5",
                         "UPDATE audit_checkpoints SET head_hash = 'x'"):
                with pytest.raises(DBAPIError):
                    with conn.begin_nested():
                        conn.execute(text(stmt))
    finally:
        sync.dispose()
