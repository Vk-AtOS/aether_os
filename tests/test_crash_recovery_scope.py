"""KAN-110: a worker starting up must not interrupt a sibling worker's live run."""
import asyncio
import time
import uuid

import pytest_asyncio
import pytest

import aether_os.core.db as db
from aether_os.core.crash_recovery import mark_orphaned_runs
from aether_os.core.models import Event, PhaseCompletion, Run

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def sf(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/c.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    async with db.get_engine().begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    yield db.get_session_factory()
    await db.get_engine().dispose()


async def test_only_stale_runs_are_interrupted(sf):
    now = time.time()
    live, dead, hot = (str(uuid.uuid4()) for _ in range(3))
    async with sf() as s:
        s.add_all([
            Run(id=live, status="running", started_at=now - 60),            # just started elsewhere
            Run(id=dead, status="running", started_at=now - 7200),          # silent for hours
            Run(id=hot, status="running", started_at=now - 7200),           # old but still emitting
        ])
        await s.flush()
        s.add_all([
            PhaseCompletion(run_id=dead, phase_name="p1", status="running", updated_at=now - 7200),
            PhaseCompletion(run_id=live, phase_name="p1", status="running", updated_at=now - 30),
            Event(run_id=hot, action="x", timestamp=now - 10),
        ])
        await s.commit()
    async with sf() as s:
        phases, runs = await mark_orphaned_runs(s, now=now, stale=900)
        await s.commit()
    assert (phases, runs) == (1, 1)
    async with sf() as s:
        from sqlalchemy import select
        status = {r.id: r.status for r in (await s.execute(select(Run))).scalars()}
    assert status == {live: "running", dead: "interrupted", hot: "running"}
