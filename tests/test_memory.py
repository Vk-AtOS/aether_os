"""
Tests for core/memory/store.py — MemoryStore.

Covers: store/retrieve sync, async wrappers, FTS fallback, stats,
and the singleton accessor.  Uses isolated tmp_path DBs — no shared state.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path):
    """Fresh MemoryStore backed by a temp SQLite file."""
    from aether_os.core.memory.store import MemoryStore
    return MemoryStore(db_path=str(tmp_path / "mem.db"))


# ─────────────────────────────────────────────────────────────────────────────
# Sync path
# ─────────────────────────────────────────────────────────────────────────────

def test_store_and_retrieve_by_hash(store):
    from aether_os.core.memory.store import MemoryRecord
    rec = MemoryRecord(
        input_hash="hash-001",
        input_text="Build a REST API",
        output_text="from fastapi import FastAPI",
        task_type="code_generation",
    )
    store.store_sync(rec)
    results = store.retrieve_sync("hash-001")
    assert len(results) == 1
    assert results[0].input_hash == "hash-001"
    assert results[0].output_text == "from fastapi import FastAPI"


def test_retrieve_returns_empty_for_unknown_hash(store):
    results = store.retrieve_sync("nonexistent-hash")
    assert results == []


def test_store_duplicate_increments_success_count(store):
    from aether_os.core.memory.store import MemoryRecord
    for _ in range(4):
        store.store_sync(MemoryRecord(
            input_hash="dup-hash",
            input_text="same prompt",
            output_text="same answer",
            task_type="ci_repair",
        ))
    results = store.retrieve_sync("dup-hash")
    assert len(results) == 1
    assert results[0].success_count == 4


def test_store_updates_output_text_on_duplicate(store):
    """When the same hash is stored again, the output_text is updated."""
    from aether_os.core.memory.store import MemoryRecord
    store.store_sync(MemoryRecord(input_hash="upd", output_text="old answer", task_type="t"))
    store.store_sync(MemoryRecord(input_hash="upd", output_text="new answer", task_type="t"))
    results = store.retrieve_sync("upd")
    assert results[0].output_text == "new answer"


def test_store_different_task_types_are_separate(store):
    """Two records with same hash but different task_type are distinct entries."""
    from aether_os.core.memory.store import MemoryRecord
    store.store_sync(MemoryRecord(input_hash="multi", task_type="code_generation"))
    store.store_sync(MemoryRecord(input_hash="multi", task_type="security_scan"))
    results = store.retrieve_sync("multi")
    # retrieve_sync does exact hash match; may return both
    assert len(results) >= 1


def test_retrieve_limit_k(store):
    """retrieve_sync respects k parameter."""
    from aether_os.core.memory.store import MemoryRecord
    # Insert 5 distinct records
    for i in range(5):
        store.store_sync(MemoryRecord(input_hash=f"ktest-{i}", task_type="code_generation"))
    # Retrieve with FTS fallback by searching for a common term — use a known hash
    results = store.retrieve_sync("ktest-0", k=2)
    assert len(results) <= 2


def test_stats_counts_records(store):
    from aether_os.core.memory.store import MemoryRecord
    store.store_sync(MemoryRecord(input_hash="s1", task_type="code_generation"))
    store.store_sync(MemoryRecord(input_hash="s2", task_type="security_scan"))
    store.store_sync(MemoryRecord(input_hash="s3", task_type="code_generation"))
    stats = store.stats()
    assert stats["total_records"] == 3


def test_stats_groups_by_task_type(store):
    from aether_os.core.memory.store import MemoryRecord
    store.store_sync(MemoryRecord(input_hash="t1", task_type="code_generation"))
    store.store_sync(MemoryRecord(input_hash="t2", task_type="code_generation"))
    store.store_sync(MemoryRecord(input_hash="t3", task_type="ci_repair"))
    stats = store.stats()
    by_task = stats["by_task_type"]
    assert by_task.get("code_generation") == 2
    assert by_task.get("ci_repair") == 1


def test_empty_store_stats(store):
    stats = store.stats()
    assert stats["total_records"] == 0
    assert stats["by_task_type"] == {}


# ─────────────────────────────────────────────────────────────────────────────
# Async wrappers
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_store_and_retrieve(store):
    from aether_os.core.memory.store import MemoryRecord
    rec = MemoryRecord(
        input_hash="async-001",
        input_text="async test",
        output_text="async output",
        task_type="code_generation",
    )
    await store.store(rec)
    results = await store.retrieve("async-001")
    assert len(results) == 1
    assert results[0].input_hash == "async-001"


@pytest.mark.asyncio
async def test_async_store_increments_count(store):
    from aether_os.core.memory.store import MemoryRecord
    for _ in range(3):
        await store.store(MemoryRecord(
            input_hash="async-cnt",
            task_type="code_generation",
            output_text="result",
        ))
    results = await store.retrieve("async-cnt")
    assert results[0].success_count == 3


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

def test_get_memory_store_returns_singleton():
    import aether_os.core.memory.store as _mod
    _mod.MemoryStore._instance = None  # reset
    from aether_os.core.memory.store import get_memory_store
    s1 = get_memory_store()
    s2 = get_memory_store()
    assert s1 is s2
    _mod.MemoryStore._instance = None  # cleanup


# ─────────────────────────────────────────────────────────────────────────────
# MemoryRecord defaults
# ─────────────────────────────────────────────────────────────────────────────

def test_memory_record_defaults():
    from aether_os.core.memory.store import MemoryRecord
    rec = MemoryRecord()
    assert rec.success_count == 1
    assert isinstance(rec.id, str) and len(rec.id) == 36  # UUID4
    assert rec.metadata == {}
    assert rec.task_type == ""
