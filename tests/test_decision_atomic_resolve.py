"""KAN-162: two simultaneous decide clicks (or a click racing the timeout) must not both succeed."""
import asyncio
import time

import pytest
import pytest_asyncio

import aether_os.core.db as db
from aether_os.core.decisions.decision_engine import AlreadyDecided, Decision, DecisionEngine
from aether_os.core.models import Organisation

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def eng(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/d.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    async with db.get_engine().begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    async with db.get_session_factory()() as s:
        s.add(Organisation(id="o1", name="O", slug="o"))
        await s.commit()
    e = DecisionEngine()
    d = Decision(id="d1", run_id="r1", org_id="o1", phase="p", title="t", timeout_seconds=60, status="pending",
                 created_at=time.time())
    await e._db_save(d)
    yield e
    await db.get_engine().dispose()


async def test_exactly_one_of_two_simultaneous_resolves_wins(eng, monkeypatch):
    real_get = eng._db_get

    async def stale_get(decision_id):          # both callers read 'pending' before either writes: the race
        d = await real_get(decision_id)
        await asyncio.sleep(0.05)
        return d
    monkeypatch.setattr(eng, "_db_get", stale_get)
    results = await asyncio.gather(eng.resolve("d1", "o1", True, "a"), eng.resolve("d1", "o1", False, "b"),
                                   return_exceptions=True)
    wins = [r for r in results if isinstance(r, Decision)]
    assert len(wins) == 1 and sum(isinstance(r, AlreadyDecided) for r in results) == 1
    stored = await real_get("d1")
    assert stored.status == wins[0].status and stored.human_choice == wins[0].human_choice


async def test_a_resolve_after_the_timeout_is_refused(eng):
    from sqlalchemy import update
    from aether_os.core.models import Decision as M
    async with db.get_session_factory()() as s:
        await s.execute(update(M).where(M.id == "d1").values(status="timeout"))
        await s.commit()
    with pytest.raises(AlreadyDecided):
        await eng.resolve("d1", "o1", True, "a")
