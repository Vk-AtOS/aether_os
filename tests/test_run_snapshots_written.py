"""KAN-161: nothing wrote Snapshot rows, so the run Snapshots tab was always empty."""
import pytest
import pytest_asyncio
from sqlalchemy import select

import aether_os.core.db as db
from aether_os.core import artifact_store as store
from aether_os.core.models import Organisation, Run, Snapshot

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def run(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/s.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    async with db.get_engine().begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    async with db.get_session_factory()() as s:
        s.add(Organisation(id="o1", name="O", slug="o"))
        s.add(Run(id="r1", org_id="o1", status="running"))
        await s.commit()
    yield "r1"
    await db.get_engine().dispose()


async def _rows():
    async with db.get_session_factory()() as s:
        return (await s.execute(select(Snapshot).order_by(Snapshot.created_at))).scalars().all()


async def test_store_artifact_writes_a_snapshot_even_when_the_embedder_is_down(run, monkeypatch):
    class Down:
        async def embed(self, _c):
            raise RuntimeError("ollama down")
    monkeypatch.setattr(store, "get_llm_client", lambda: Down())
    await store.get_artifact_store().store_artifact(run, "app/main.py", "print(1)", org_id="o1")
    rows = await _rows()
    assert [(r.run_id, r.file_path, r.content) for r in rows] == [("r1", "app/main.py", "print(1)")]


async def test_unchanged_content_is_not_duplicated_and_changes_are_kept(run):
    s = store.get_artifact_store()
    assert await s.record_snapshot(run, "a.py", "v1") is True
    assert await s.record_snapshot(run, "a.py", "v1") is False
    assert await s.record_snapshot(run, "a.py", "v2") is True
    assert [r.content for r in await _rows()] == ["v1", "v2"]


async def test_snapshots_are_bounded(run, monkeypatch):
    s = store.get_artifact_store()
    assert await s.record_snapshot(run, "big.bin", "x" * (store.SNAPSHOT_MAX_BYTES + 1)) is False
    monkeypatch.setattr(store, "SNAPSHOT_MAX_PER_RUN", 2)
    await s.record_snapshot(run, "1", "a")
    await s.record_snapshot(run, "2", "b")
    assert await s.record_snapshot(run, "3", "c") is False
