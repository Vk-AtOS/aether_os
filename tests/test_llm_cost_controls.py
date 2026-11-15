"""KAN-116 / D6: spend cap, kill switch, plan required, no free providers, one budget row per month."""
import asyncio
import time

import pytest
import pytest_asyncio

import aether_os.core.db as db
from aether_os.core.errors import LLMUnavailable
from aether_os.core.llm import budget, controls
from aether_os.core.model_router import ModelRouter
from aether_os.core.models import Organisation

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def dbenv(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/b.db")
    monkeypatch.delenv("LLM_KILL_SWITCH", raising=False)
    monkeypatch.setattr(controls, "_orgs", {})
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    async with db.get_engine().begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    async with db.get_session_factory()() as s:   # an org that does not exist is refused (fail closed)
        for oid in ("org-x", "org-y", "org-z"):
            s.add(Organisation(id=oid, name=oid, slug=oid, plan="starter"))
        await s.commit()
    yield
    await db.get_engine().dispose()


async def test_kill_switch_blocks_every_call(dbenv, monkeypatch):
    monkeypatch.setenv("LLM_KILL_SWITCH", "1")
    with pytest.raises(LLMUnavailable, match="kill switch"):
        await ModelRouter().call("hi", org_id=None)


async def test_monthly_cap_is_a_hard_stop_for_every_plan(dbenv):
    bm = budget.get_budget_manager()
    await bm.record_usage("org-x", input_tokens=budget._PLAN_BUDGETS["starter"], output_tokens=0)
    ok, reason, _ = await bm.check_budget("org-x", "starter")
    assert ok is False and "exhausted" in reason
    with pytest.raises(LLMUnavailable, match="budget exceeded"):
        await ModelRouter().call("hi", org_id="org-x", plan="starter")


async def test_missing_plan_is_resolved_or_refused(dbenv):
    with pytest.raises(LLMUnavailable, match="plan"):
        await ModelRouter().call("hi", org_id="no-such-org")


async def test_concurrent_first_usage_makes_one_row_and_counts_everything(dbenv):
    bm = budget.get_budget_manager()
    await asyncio.gather(*[bm.record_usage("org-y", 10, 5) for _ in range(8)])
    u = await bm.get_usage("org-y", time.strftime("%Y-%m"), strict=True)
    assert u["input_tokens"] == 80 and u["output_tokens"] == 40 and u["runs"] == 8


async def test_budget_store_failure_fails_closed(dbenv, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(budget.TokenBudgetManager, "get_usage", boom)
    with pytest.raises(LLMUnavailable, match="unavailable"):
        await ModelRouter().call("hi", org_id="org-z", plan="starter")
