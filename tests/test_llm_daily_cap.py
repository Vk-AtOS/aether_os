"""KAN-116: a daily spend cap so a looping agent cannot burn the month's allowance in one day."""
import pytest
import pytest_asyncio

import aether_os.core.db as db
from aether_os.core.errors import LLMUnavailable
from aether_os.core.llm import budget, controls, guard
from aether_os.core.llm.plans import PLAN_LIMITS
from aether_os.core.models import Organisation

pytestmark = [pytest.mark.asyncio, pytest.mark.platform_budget]


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/d.db")
    monkeypatch.delenv("LLM_KILL_SWITCH", raising=False)
    monkeypatch.delenv("LLM_DAILY_SHARE", raising=False)
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    monkeypatch.setattr(controls, "_orgs", {})
    monkeypatch.setattr(controls, "_flag", (0.0, False))
    monkeypatch.setattr(budget, "_alerted", set())
    async with db.get_engine().begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    async with db.get_session_factory()() as s:
        s.add(Organisation(id="o1", name="O", slug="o", plan="starter"))
        await s.commit()
    yield
    await db.get_engine().dispose()


async def _spend(usd):
    await budget.get_budget_manager().record_usage("o1", 0, int(usd / 15 * 1_000_000), model="claude-sonnet-4-6")


def test_daily_cap_is_a_share_of_the_month_with_a_floor(monkeypatch):
    monkeypatch.delenv("LLM_DAILY_SHARE", raising=False)
    assert budget.daily_cap_usd(50.0) == 12.5
    assert budget.daily_cap_usd(5.0) == 2.0          # a small plan is not locked out after one run
    assert budget.daily_cap_usd(1.0) == 1.0          # never above the monthly cap
    monkeypatch.setenv("LLM_DAILY_SHARE", "1")
    assert budget.daily_cap_usd(50.0) == 50.0


async def test_a_looping_agent_is_stopped_for_the_day_long_before_the_month_is_gone(env):
    month = PLAN_LIMITS["starter"].usd                 # $50, daily cap $12.50
    await _spend(month * 0.2)                          # $10 today: fine
    await guard.admit("o1", "starter", "hi", None, 100)
    await _spend(month * 0.1)                          # $15 today
    with pytest.raises(LLMUnavailable, match="Daily AI allowance"):
        await guard.admit("o1", "starter", "hi", None, 100)
    async with db.get_session_factory()() as s:        # tomorrow is a new row: yesterday's spend does not carry over
        from aether_os.core.models_ops import LlmDailyUsage
        s.add(LlmDailyUsage(org_id="o1", day="2020-01-01", cost_usd=99.0))
        await s.commit()
    assert await budget.get_budget_manager().check_budget("o1", "starter") is not None


async def test_another_organisation_is_not_limited_by_this_ones_day(env):
    async with db.get_session_factory()() as s:
        s.add(Organisation(id="o2", name="P", slug="p", plan="starter"))
        await s.commit()
    await _spend(14.0)
    ok, _reason, _hint = await budget.get_budget_manager().check_budget("o2", "starter")
    assert ok is True
