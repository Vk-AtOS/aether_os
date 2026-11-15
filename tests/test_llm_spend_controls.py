"""KAN-116 / D6: USD cap with 80% alert, admin kill switch, sensitive data, plan on every call."""
import time

import pytest
import pytest_asyncio
from sqlalchemy import select

import aether_os.core.db as db
from aether_os.core.errors import LLMUnavailable
from aether_os.core.llm import budget, controls, guard
from aether_os.core.llm.plans import PLAN_LIMITS
from aether_os.core.llm.sensitivity import classify
from aether_os.core.models import Notification, Organisation

pytestmark = [pytest.mark.asyncio, pytest.mark.platform_budget]
CARD = "4111 1111 1111 1111"  # Luhn-valid test number


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/c.db")
    monkeypatch.delenv("LLM_KILL_SWITCH", raising=False)
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
    # claude-sonnet-4-6 output is $15/M tokens
    await budget.get_budget_manager().record_usage("o1", 0, int(usd / 15 * 1_000_000), model="claude-sonnet-4-6")


async def test_every_plan_the_product_sells_has_an_allowance():
    for plan in ("free", "trial", "starter", "growth", "pro", "enterprise"):
        assert plan in PLAN_LIMITS and PLAN_LIMITS[plan].usd > 0 and PLAN_LIMITS[plan].tokens > 0


async def test_usd_cap_alerts_at_80_percent_and_stops_at_100(env):
    cap = PLAN_LIMITS["starter"].usd
    await _spend(cap * 0.5)
    assert (await guard.admit("o1", None, "hi", None, 100)).plan == "starter"   # plan came from the org row
    await _spend(cap * 0.31)
    await guard.admit("o1", "starter", "hi", None, 100)
    async with db.get_session_factory()() as s:
        alerts = (await s.execute(select(Notification).where(Notification.org_id == "o1"))).scalars().all()
    assert len(alerts) == 1 and alerts[0].type.startswith("llm_budget_80")
    await guard.admit("o1", "starter", "hi", None, 100)                           # no second alert
    async with db.get_session_factory()() as s:
        assert len((await s.execute(select(Notification))).scalars().all()) == 1
    await _spend(cap * 0.2)
    with pytest.raises(LLMUnavailable, match="exhausted"):
        await guard.admit("o1", "starter", "hi", None, 100)


async def test_a_huge_request_cannot_overshoot_the_cap(env):
    await _spend(PLAN_LIMITS["starter"].usd * 0.99)
    with pytest.raises(LLMUnavailable, match="exhausted"):
        await guard.admit("o1", "starter", "x" * 40_000, None, 200_000)


async def test_per_org_cap_override_beats_the_plan_default(env):
    async with db.get_session_factory()() as s:
        org = await s.get(Organisation, "o1")
        org.llm_monthly_cap_usd = 1.0
        await s.commit()
    await _spend(1.5)
    with pytest.raises(LLMUnavailable, match="exhausted"):
        await guard.admit("o1", "starter", "hi", None, 100)


async def test_org_and_global_kill_switches(env, monkeypatch):
    async with db.get_session_factory()() as s:
        (await s.get(Organisation, "o1")).llm_disabled = True
        await s.commit()
    with pytest.raises(LLMUnavailable, match="disabled for this organisation"):
        await guard.admit("o1", "starter", "hi", None, 100)
    monkeypatch.setattr(controls, "_flag", (time.monotonic(), True))   # what a Redis flag change looks like
    with pytest.raises(LLMUnavailable, match="kill switch"):
        await guard.admit(None, None, "hi", None, 100)


async def test_missing_org_unknown_plan_and_calls_without_org(env):
    with pytest.raises(LLMUnavailable, match="plan"):
        await guard.admit("ghost", None, "hi", None, 100)
    with pytest.raises(LLMUnavailable, match="Unknown plan"):
        await guard.admit("o1", "platinum", "hi", None, 100)
    assert (await guard.admit(None, None, "hi", None, 100)).plan == "platform"


async def test_sensitive_prompts_are_classified_and_never_go_to_openrouter(env, monkeypatch):
    assert "card_number" in classify(f"charge card {CARD} now")
    assert "private_key" in classify("-----BEGIN RSA PRIVATE KEY-----\nabc")
    assert classify("password = hunter2hunter2") == ["credential_assignment"]
    assert classify("add a status field and a 4242 selector") == []
    assert (await guard.admit("o1", "starter", f"card {CARD}", None, 100)).sensitive_reasons and True

    from aether_os.core import model_router as mr
    from aether_os.core.model_router_providers import ModelSpec
    seen = []

    async def provider(self, spec, *a, **k):
        seen.append(spec.provider)
        return "ok"

    chain = [ModelSpec("openrouter", "x/y:free", 5, 1), ModelSpec("openrouter", "paid/model", 5, 1),
             ModelSpec("anthropic", "claude-sonnet-4-6", 5, 1)]
    monkeypatch.setenv("ALLOW_COMMUNITY_LLM", "1")
    monkeypatch.setattr(mr, "get_fallback_chain", lambda: list(chain))
    monkeypatch.setattr(mr.ModelRouter, "_call_provider", provider)
    monkeypatch.setattr(mr, "_provider_key", lambda *a: _async("k"))
    monkeypatch.setattr(mr, "_is_provider_dead", lambda *a, **k: False)
    monkeypatch.setattr(mr, "_breaker_scope", lambda *a: _async(""))
    await mr.ModelRouter().call(f"card {CARD}", org_id="o1", plan="starter")
    assert seen == ["anthropic"]                       # community opt-in is on, yet sensitive data skipped it
    seen.clear()
    await mr.ModelRouter().call("hello", org_id="o1", plan="starter")
    assert seen == ["openrouter"]                      # ordinary prompt: opt-in chain order preserved


async def _async(v):
    return v


async def test_llm_client_passes_the_org_plan(env, monkeypatch):
    from aether_os.core.llm.client import LLMClient
    from aether_os.core import model_router as mr
    got = {}

    class R:
        last_model = "m"
        async def call(self, **kw):
            got.update(kw)
            return "ok", "anthropic"

    monkeypatch.setattr(mr, "get_router", lambda: R())
    await LLMClient().call("hi", org_id="o1")
    assert got["plan"] == "starter"


# ── admin endpoints (real gateway, SQLite) ────────────────────────────────────

def test_admin_endpoints_are_role_gated_and_move_the_switches(gw):
    from aether_os.core.llm import controls as c
    owner = gw.register("llmctl")
    member = gw.user_with_role("member", owner.org_id)
    admin = gw.user_with_role("admin", owner.org_id)
    sup = gw.user_with_role("superadmin", owner.org_id)
    assert gw.client.post("/admin/llm/kill-switch", headers=admin.auth, json={"on": True}).status_code == 403
    assert gw.client.post("/settings/llm/kill-switch", headers=member.auth, json={"on": True}).status_code == 403
    assert gw.client.put(f"/admin/llm/orgs/{owner.org_id}/cap", headers=admin.auth,
                         json={"monthly_cap_usd": 1}).status_code == 403
    # org admin stops their own org
    assert gw.client.post("/settings/llm/kill-switch", headers=admin.auth, json={"on": True}).json() == {"llm_disabled": True}
    assert gw.sql("SELECT llm_disabled FROM organisations WHERE id = ?", (owner.org_id,))[0][0] == 1
    assert gw.client.get("/settings/llm/usage", headers=member.auth).json()["llm_disabled"] is True
    # superadmin cap override and the global switch (Redis-backed, so every worker sees it)
    assert gw.client.put(f"/admin/llm/orgs/{owner.org_id}/cap", headers=sup.auth,
                         json={"monthly_cap_usd": 7.5}).json()["monthly_cap_usd"] == 7.5
    assert gw.client.get("/settings/llm/usage", headers=member.auth).json()["cap_usd"] == 7.5
    r = gw.client.post("/admin/llm/kill-switch", headers=sup.auth, json={"on": True})
    try:
        assert r.status_code in (200, 503)   # 503 = no Redis here: the switch must say it did not move
        if r.status_code == 200:
            assert gw.client.get("/admin/llm/status", headers=sup.auth).json()["global_kill_switch"] is True
    finally:
        gw.client.post("/admin/llm/kill-switch", headers=sup.auth, json={"on": False})
        c._flag = (0.0, False)
