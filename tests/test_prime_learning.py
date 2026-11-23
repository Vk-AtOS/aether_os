"""KAN-229: one learning loop over corrections, golden builds and fix memory. For each learner: a use is recorded
when an item goes into a prompt (or a fix is replayed), the outcome is recorded, an item that keeps failing is retired
and a retired item is not put in again; admins alone retire and restore; everything is per organisation."""
# ruff: noqa: F811
from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from aether_os.core import db
from aether_os.core import fix_memory as fm
from aether_os.core.models import GoldenBuild
from aether_os.core.models_memory import FixMemory
from aether_os.core.run_context import ACTIVE_RUN_ID
from aether_os.gateway.routers import prime_corrections_router as corr_api
from aether_os.gateway.routers import prime_learning_router as api
from aether_os.prime.learning import adapters, loop, metrics
from aether_os.prime.learning.models import LearningBuildOutcome, LearningItemState, LearningUse
from aether_os.tests.prime_helpers import (  # noqa: F401
    act, ADMIN, ALICE, API_KEY, BOB, BOB_IDS, counting, grant, MEMBER, ORG, OTHER_ORG, OUTSIDER, svc,
)

pytestmark = pytest.mark.asyncio
ERR = "src/pages/TaskPage.tsx(1,1): error TS17008: JSX element 'div' has no corresponding closing tag.\n"
PATCH = {"file": "src/pages/TaskPage.tsx", "find": "<div><p>hi</p>", "replace": "<div><p>hi</p></div>"}


@pytest_asyncio.fixture
async def learn(svc):
    async with db.get_engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=[
            t.__table__ for t in (LearningUse, LearningItemState, LearningBuildOutcome, GoldenBuild, FixMemory)]))
    yield svc


async def uses(kind):
    async with db.get_session_factory()() as s:
        return (await s.execute(select(LearningUse).where(LearningUse.kind == kind)
                                .order_by(LearningUse.used_at))).scalars().all()


async def ask(user=API_KEY):
    return await corr_api.relevant(agent="payables", action_type="invoice.approve", q="", k=3, also=[], user=user)


async def asked():
    return [c["id"] for c in (await ask())["corrections"]]


async def propose(svc, approve=True, edit=False):
    """The proposer submits the next request after reading the corrections; an approver decides it."""
    from aether_os.prime.edits import edit_request
    req = (await svc.submit(act("invoice.approve", amount=Decimal("250"), currency="INR",
                                params={"agent": "payables", "note": "april"}), ORG, "counting"))["request"]
    if edit:
        req = await edit_request(svc, req["id"], BOB, BOB_IDS, ORG, req["request_hash"], "too much",
                                 amount=Decimal("200"))
        return await svc.decide(req["id"], ALICE, [ALICE, "alice@a.test"], ORG, req["request_hash"], approve=approve)
    return await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=approve)


async def a_correction(svc):
    from aether_os.prime.edits import edit_request
    req = (await svc.submit(act("invoice.approve", amount=Decimal("250"), currency="INR",
                                params={"agent": "payables", "note": "march"}), ORG, "counting"))["request"]
    await edit_request(svc, req["id"], BOB, BOB_IDS, ORG, req["request_hash"], "wrong amount, ask x@y.test",
                       amount=Decimal("300"))


# ── corrections ──────────────────────────────────────────────────────────────────────────────────────────────────

async def test_correction_use_and_outcome_are_recorded_and_failing_ones_retire(learn, counting):
    svc = learn
    await grant()
    await a_correction(svc)
    out = await ask()
    cid = out["corrections"][0]["id"]
    assert "x@y.test" not in out["prompt_block"]                       # pseudonymised before the prompt
    assert [(u.item_id, u.helped) for u in await uses("correction")] == [(cid, None)]

    await propose(svc, approve=True)                                   # approved unchanged: it helped
    assert [u.helped for u in await uses("correction")] == [True]
    await propose(svc, approve=True)                                   # no pending use left: nothing changes
    assert [u.helped for u in await uses("correction")] == [True]

    for decide in ({"approve": False}, {"approve": False}, {"approve": True, "edit": True}):
        assert cid in await asked()
        await propose(svc, **decide)                                   # rejected or edited: did not help
    assert [u.helped for u in await uses("correction") if u.item_id == cid] == [True, False, False, False]
    assert cid not in await asked()                                    # retired: no longer in the prompt
    assert len([u for u in await uses("correction") if u.item_id == cid]) == 4   # and not recorded as used

    listed = (await api.items(kind=["correction"], user=MEMBER))["kinds"]["correction"]
    item = next(i for i in listed if i["id"] == cid)
    assert item["retired"] and item["retired_by"] == "prime"
    assert (item["used"], item["helped"], item["help_rate"]) == (4, 1, 0.25)
    assert "x@y.test" not in item["text"] and item["scope"] == "payables · invoice.approve"

    with pytest.raises(HTTPException) as e:                            # restore is owner/admin only
        await api.restore("correction", cid, user=MEMBER)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:                            # another organisation's admin
        await api.restore("correction", cid, user={**ADMIN, "org_id": OTHER_ORG})
    assert e.value.status_code == 404
    assert (await api.restore("correction", cid, user=ADMIN))["retired"] is False
    assert cid in await asked()                                        # back in the prompt
    await api.retire("correction", cid, user=ADMIN)
    assert cid not in await asked()
    assert (await api.items(kind=["correction"], user=OUTSIDER))["kinds"]["correction"] == []


# ── golden builds ────────────────────────────────────────────────────────────────────────────────────────────────

async def golden(org, name):
    async with db.get_session_factory()() as s:
        g = GoldenBuild(run_id=f"run-{name}", org_id=org, domain="general", project_name=name, user_rating=4.5,
                        quality_score=80, p04_sample="class A: pass", p05_sample="", is_active=True,
                        created_at=datetime.utcnow())
        s.add(g)
        await s.commit()
        return g.id


async def test_golden_use_is_recorded_per_run_and_settled_by_the_build_then_retired(learn):
    mine, theirs = await golden(ORG, "crm"), await golden(OTHER_ORG, "theirs")
    for n in range(3):
        token = ACTIVE_RUN_ID.set(f"r{n}")
        try:
            got = await adapters.golden_for_prompt("general", 2, ORG, "p04a_backend_codegen")
        finally:
            ACTIVE_RUN_ID.reset(token)
        assert [g["id"] for g in got] == [mine]                         # never another org's build
        assert await loop.record_build(ORG, f"r{n}", built=False, first_pass=False, rounds=3)
    assert [(u.ref, u.helped, u.scope) for u in await uses("golden")] == [
        (f"r{n}", False, "p04a_backend_codegen") for n in range(3)]
    assert await adapters.golden_for_prompt("general", 2, ORG, "p05_frontend") == []   # retired
    assert len(await uses("golden")) == 3
    assert not await loop.record_build(ORG, "r0", built=True, first_pass=True, rounds=1)   # first build of a run counts
    with pytest.raises(HTTPException) as e:
        await api.retire("golden", theirs, user=ADMIN)                 # not this organisation's
    assert e.value.status_code == 404
    await api.restore("golden", mine, user=ADMIN)
    token = ACTIVE_RUN_ID.set("r9")
    try:
        assert len(await adapters.golden_for_prompt("general", 2, ORG, "p05_frontend")) == 1
    finally:
        ACTIVE_RUN_ID.reset(token)
    await loop.record_build(ORG, "r9", built=True, first_pass=True, rounds=1)
    assert (await uses("golden"))[-1].helped is True


async def test_build_loop_records_the_runs_build(monkeypatch):
    from aether_os.phases.p05_frontend import build_loop
    seen = []

    async def rounds(*a):
        return {"success": True, "built": True, "tsc_errors": 0, "tsc_messages": [], "rounds": 1}

    async def record(*a):
        seen.append(a)
        return True
    monkeypatch.setitem(os.environ, "ENVIRONMENT", "development")
    monkeypatch.setattr(build_loop, "_build_rounds", rounds)
    monkeypatch.setattr(build_loop.learning, "record_build", record)
    token = ACTIVE_RUN_ID.set("run-7")
    try:
        await build_loop.run_build_loop(None, org_id=ORG)
    finally:
        ACTIVE_RUN_ID.reset(token)
    assert seen == [(ORG, "run-7", True, True, 1)]


# ── fix memory ───────────────────────────────────────────────────────────────────────────────────────────────────

async def test_fix_replay_use_and_outcome_are_recorded_and_a_retired_fix_is_not_replayed(learn, tmp_path):
    from aether_os.phases.p05_frontend.fix_memory_hook import RoundMemory
    page = tmp_path / "src/pages/TaskPage.tsx"
    page.parent.mkdir(parents=True)
    sig = fm.parse_errors(ERR)[0]["signature"]
    await fm.record(ORG, sig, "tsx:pages", [PATCH])

    async def build_once(still_failing):
        page.write_text("<div><p>hi</p>\n")
        mem = RoundMemory(ORG, tmp_path, lambda d, p: True)
        applied = await mem.try_known(ERR)
        await mem.settle(ERR if still_failing else "")
        return applied

    token = ACTIVE_RUN_ID.set("run-f")
    try:
        assert await build_once(still_failing=False) == 1
        assert await build_once(still_failing=True) == 1
    finally:
        ACTIVE_RUN_ID.reset(token)
    assert [(u.item_id, u.ref, u.helped, u.scope) for u in await uses("fix")] == [
        (sig, "run-f", True, "tsx:pages"), (sig, "run-f", False, "tsx:pages")]
    item = (await api.items(kind=["fix"], user=MEMBER))["kinds"]["fix"][0]
    assert (item["id"], item["used"], item["helped"], item["help_rate"]) == (sig, 2, 1, 0.5)
    with pytest.raises(HTTPException) as e:
        await api.retire("fix", sig, user=MEMBER)
    assert e.value.status_code == 403
    await api.retire("fix", sig, user=ADMIN)
    assert await build_once(still_failing=True) == 0                   # retired: not replayed
    assert len(await uses("fix")) == 2


async def test_recording_never_breaks_the_caller_when_the_tables_are_missing(svc):
    """The approval and build paths must go on when the learning tables cannot be written."""
    assert await loop.record_use(ORG, "fix", ["s"]) == 0
    assert await loop.record_outcome(ORG, "fix", True, item_ids=["s"]) == 0
    assert await loop.retired_ids(ORG, "fix") == set()
    assert await loop.record_build(ORG, "r", True, True, 1) is False


# ── metrics ──────────────────────────────────────────────────────────────────────────────────────────────────────

async def test_metrics_give_help_rate_per_kind_and_week_and_the_trend(learn, counting):
    svc = learn
    await grant()
    await a_correction(svc)                                            # 1 correction, 1 decided below
    await ask()
    await propose(svc, approve=True)
    await loop.record_use(ORG, "fix", ["s1", "s2"], ref="r1")
    await loop.record_outcome(ORG, "fix", True, ref="r1", item_ids=["s1"])
    await loop.record_outcome(ORG, "fix", False, ref="r1", item_ids=["s2"])
    await loop.record_build(ORG, "r1", True, True, 1)
    await loop.record_build(ORG, "r2", True, False, 2)
    await loop.record_use(OTHER_ORG, "fix", ["s3"], ref="r3")
    await loop.record_outcome(OTHER_ORG, "fix", True, ref="r3")

    out = await api.learning_metrics(weeks=4, user=MEMBER)
    assert len(out["weeks"]) == 4 and out["weeks"][-1]["week"] == metrics.week_of(datetime.utcnow())
    now = out["weeks"][-1]
    assert now["kinds"]["correction"] == {"settled": 1, "helped": 1, "help_rate": 1.0}
    assert now["kinds"]["fix"] == {"settled": 2, "helped": 1, "help_rate": 0.5}   # not the other org's
    assert now["kinds"]["golden"]["help_rate"] is None
    assert (now["builds"], now["first_pass_rate"]) == (2, 0.5)
    assert (now["corrections"], now["decided"], now["correction_rate"]) == (1, 1, 1.0)
    assert out["weeks"][0]["first_pass_rate"] is None
    assert out["totals"]["fix"]["help_rate"] == 0.5
    assert metrics.week_of(datetime(2026, 11, 26)) == "2026-11-23"      # Monday
    assert metrics.week_of(datetime(2026, 11, 23) - timedelta(seconds=1)) == "2026-11-16"
