"""KAN-170: council remediation targets real stages; a council that did not run is never a pass."""
import time

import pytest
import pytest_asyncio
from sqlalchemy import select

import aether_os.core.db as db
from aether_os.core.models import Run
from aether_os.orchestrator import artifact_collector as ac
from aether_os.orchestrator.phase_sequence import PHASE_SUPERVISORS

pytestmark = pytest.mark.asyncio


def test_every_remediation_target_is_a_real_stage():
    for criterion, stages in ac._CRITERION_TO_PHASES.items():
        for stage in stages:
            assert stage in PHASE_SUPERVISORS, f"{criterion} -> {stage} is not a stage"


@pytest_asyncio.fixture
async def run_id(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/c.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    async with db.get_engine().begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    async with db.get_session_factory()() as s:
        s.add(Run(id="r1", status="running", started_at=time.time()))
        await s.commit()
    yield "r1"
    await db.get_engine().dispose()


async def test_council_timeout_is_visible_in_run_data_and_not_reported_as_passed(run_id, monkeypatch):
    events = []

    async def fake_publish(rid, ev): events.append(ev)
    monkeypatch.setattr(ac, "publish_event", fake_publish)

    import asyncio
    class HangingCouncil:
        async def run(self, **kw): raise asyncio.TimeoutError
    monkeypatch.setattr(ac, "DeliveryCouncil", HangingCouncil)
    await ac.delivery_council_check(run_id, "p", "raw", "general", {}, None, {})
    async with db.get_session_factory()() as s:
        run = (await s.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert run.council_delivery["status"] == "unavailable" and run.council_delivery["passed"] is None
    assert "did not run" in run.message
    types = [e["type"] for e in events]
    assert "council_delivery_unavailable" in types and "council_delivery_passed" not in types


async def test_unavailable_council_notifies_the_org_and_writes_the_ledger(run_id, monkeypatch):
    # KAN-170: an unreviewed delivery must leave a ledger entry and an in-app notification, not just an event.
    from aether_os.core.models import Notification

    async def fake_publish(rid, ev): pass
    monkeypatch.setattr(ac, "publish_event", fake_publish)
    logged = []

    class FakeLedger:
        async def async_log_audit_event(self, **kw): logged.append(kw)
    monkeypatch.setattr(ac, "get_ledger", lambda: FakeLedger())

    class BrokenCouncil:
        async def run(self, **kw): raise RuntimeError("model down")
    monkeypatch.setattr(ac, "DeliveryCouncil", BrokenCouncil)
    await ac.delivery_council_check(run_id, "Shop", "raw", "general", {}, "org_abc", {})

    assert logged and logged[0]["action"] == "council_delivery_unavailable" and logged[0]["org_id"] == "org_abc"
    async with db.get_session_factory()() as s:
        notes = (await s.execute(select(Notification).where(Notification.org_id == "org_abc"))).scalars().all()
    assert [n.type for n in notes] == ["council_unavailable"] and "Shop" in notes[0].title
