"""Audit chain: real hashing, real verify(), on an isolated SQLite database."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

import aether_os.core.db as db
from aether_os.core.audit import chain
from aether_os.core.audit.chain import AuditChainEntry
from aether_os.core.audit.ledger import DecisionLedger
from aether_os.core.models import AuditLog

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def ledger_db(tmp_path, monkeypatch):
    """Point core.db at a throwaway SQLite file so the dev ledger is never touched."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/chain.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(
            c, tables=[AuditChainEntry.__table__, AuditLog.__table__]))
    yield db.get_session_factory()
    await engine.dispose()


async def _fill(n: int = 5) -> None:
    for i in range(n):
        await chain.append(actor=f"user-{i}", action="thing.done", payload={"i": i, "b": [1, 2]})


async def _tamper(sf, seq: int, **values) -> None:
    async with sf() as s:
        await s.execute(update(AuditChainEntry).where(AuditChainEntry.seq == seq).values(**values))
        await s.commit()


async def test_empty_chain_verifies(ledger_db):
    result = await chain.verify()
    assert result.ok and result.entries_checked == 0


async def test_intact_chain_verifies_and_links(ledger_db):
    await _fill(5)
    result = await chain.verify()
    assert result.ok and result.entries_checked == 5 and result.broken_seq is None

    entries = await chain.read_entries()
    assert [e["seq"] for e in entries] == [1, 2, 3, 4, 5]
    assert entries[0]["prev_hash"] == chain.GENESIS_HASH
    for prev, cur in zip(entries, entries[1:]):
        assert cur["prev_hash"] == prev["entry_hash"]
    assert entries[2]["payload"] == {"i": 2, "b": [1, 2]}


@pytest.mark.parametrize("field,value", [
    ("payload", '{"i":999}'),
    ("actor", "mallory"),
    ("action", "thing.undone"),
    ("timestamp", 1.0),
    ("prev_hash", "f" * 64),
    ("entry_hash", "e" * 64),
])
@pytest.mark.parametrize("seq", [1, 3, 5])
async def test_editing_any_field_of_any_entry_breaks_verify_there(ledger_db, seq, field, value):
    await _fill(5)
    await _tamper(ledger_db, seq, **{field: value})
    result = await chain.verify()
    assert not result.ok
    assert result.broken_seq == seq
    assert result.entries_checked == seq - 1
    assert result.reason


async def test_edit_with_recomputed_hash_breaks_at_next_entry(ledger_db):
    await _fill(5)
    async with ledger_db() as s:
        row = (await s.execute(select(AuditChainEntry).where(AuditChainEntry.seq == 2))).scalar_one()
    forged = chain.compute_entry_hash(row.prev_hash, row.timestamp, "mallory", row.action, row.payload)
    await _tamper(ledger_db, 2, actor="mallory", entry_hash=forged)
    result = await chain.verify()
    assert not result.ok and result.broken_seq == 3


async def test_deleting_a_middle_entry_is_detected(ledger_db):
    await _fill(5)
    async with ledger_db() as s:
        await s.execute(delete(AuditChainEntry).where(AuditChainEntry.seq == 3))
        await s.commit()
    result = await chain.verify()
    assert not result.ok and result.broken_seq == 4 and "missing" in result.reason


async def test_fork_is_rejected_by_the_database(ledger_db):
    await _fill(2)
    async with ledger_db() as s:
        with pytest.raises(IntegrityError):
            await s.execute(insert(AuditChainEntry).values(
                seq=99, timestamp=1.0, actor="a", action="b", payload="{}",
                prev_hash=chain.GENESIS_HASH, entry_hash="d" * 64))


async def test_orm_update_and_delete_are_refused(ledger_db):
    await _fill(1)
    async with ledger_db() as s:
        row = await s.get(AuditChainEntry, 1)
        row.actor = "mallory"
        with pytest.raises(RuntimeError, match="append-only"):
            await s.commit()
    async with ledger_db() as s:
        row = await s.get(AuditChainEntry, 1)
        await s.delete(row)
        with pytest.raises(RuntimeError, match="append-only"):
            await s.commit()
    assert (await chain.verify()).ok


async def test_module_api_has_no_update_or_purge():
    names = [n for n in dir(chain) + dir(DecisionLedger)
             if any(w in n.lower() for w in ("purge", "delete", "remove", "truncate"))]
    assert names == []


async def test_hash_is_deterministic_and_covers_all_five_fields():
    base = ("p" * 64, 1700000000.5, "actor", "action", '{"a":1}')
    h = chain.compute_entry_hash(*base)
    assert h == chain.compute_entry_hash(*base) and len(h) == 64
    for i, other in enumerate(("q" * 64, 1700000000.6, "actor2", "action2", '{"a":2}')):
        changed = list(base)
        changed[i] = other
        assert chain.compute_entry_hash(*changed) != h
    assert chain.canonical_payload({"b": 1, "a": 2}) == chain.canonical_payload({"a": 2, "b": 1})


async def test_log_audit_event_writes_chain_entry_and_audit_log_row(ledger_db):
    ledger = DecisionLedger()
    await ledger.async_log_audit_event("org-1", "user-1", "login", "session", "s-1",
                                       {"k": "v"}, "127.0.0.1")
    await ledger.async_log_audit_event("org-1", "user-2", "logout")
    assert (await chain.verify()).entries_checked == 2

    entries = await chain.read_entries()
    assert entries[0]["actor"] == "user-1" and entries[0]["action"] == "login"
    assert entries[0]["payload"]["org_id"] == "org-1"
    assert entries[0]["payload"]["metadata"] == {"k": "v"}

    logs = await ledger.async_get_audit_logs("org-1")
    assert logs["total"] == 2
    async with ledger_db() as s:
        linked = (await s.execute(select(AuditLog.prev_hash))).scalars().all()
    assert sorted(linked) == sorted(e["entry_hash"] for e in entries)
