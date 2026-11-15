"""KAN-15 / KAN-116: restricted data never reaches a free or third-party pool, by ANY path; platform calls have a budget."""
import pytest
import pytest_asyncio

import aether_os.core.db as db
from aether_os.core import model_router as mr
from aether_os.core.errors import LLMUnavailable
from aether_os.core.llm import budget, controls, guard
from aether_os.core.llm.data_policy import effective_level, filter_chain, permits
from aether_os.core.llm.plans import PLATFORM_ORG
from aether_os.core.model_router_providers import ModelSpec
from aether_os.core.models import Organisation

pytestmark = [pytest.mark.asyncio, pytest.mark.platform_budget]
CARD = "4111 1111 1111 1111"


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/p.db")
    monkeypatch.delenv("LLM_KILL_SWITCH", raising=False)
    monkeypatch.delenv("ALLOW_COMMUNITY_LLM", raising=False)
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


def test_levels_fail_closed_and_policy_table():
    assert effective_level(None, "hello") == "internal"
    assert effective_level("public", "hello") == "public"
    assert effective_level("secret", "hello") == "restricted"               # not a level -> restricted
    assert effective_level("public", f"card {CARD}") == "restricted"        # the caller cannot lower it
    assert not permits("openrouter", "x:free", "internal")                  # community off by default
    assert not permits("gemini", "foo:free", "restricted")


def test_restricted_never_community_even_when_opted_in(monkeypatch):
    monkeypatch.setenv("ALLOW_COMMUNITY_LLM", "1")
    specs = [ModelSpec("openrouter", "a:free", 1, 1), ModelSpec("openrouter", "paid/x", 1, 1), ModelSpec("anthropic", "c", 1, 1),
             ModelSpec("gemini", "g:free", 1, 1)]
    assert [s.provider for s in filter_chain(specs, "restricted")] == ["anthropic"]
    assert len(filter_chain(specs, "internal")) == 4


async def _async(v):
    return v


async def test_org_stored_key_cannot_reinject_openrouter_for_restricted_data(env, monkeypatch):
    """Root cause: the sensitivity filter ran BEFORE _apply_org_chain_overrides, which appends an openrouter :free
    spec when the org stored an OpenRouter key; the prompt then went to the community pool."""
    seen = []

    async def provider(self, spec, *a, **k):
        seen.append(spec.provider)
        return "ok"

    async def inject(chain, org_id):
        return chain + [ModelSpec("openrouter", "minimax/minimax-m2.5:free", 5, 1)]
    monkeypatch.setenv("ALLOW_COMMUNITY_LLM", "1")
    monkeypatch.setattr(mr, "get_fallback_chain", lambda: [ModelSpec("anthropic", "claude-sonnet-4-6", 5, 1)])
    monkeypatch.setattr(mr, "_apply_org_chain_overrides", inject)
    monkeypatch.setattr(mr.ModelRouter, "_call_provider", provider)
    monkeypatch.setattr(mr, "_provider_key", lambda *a: _async("k"))
    monkeypatch.setattr(mr, "_is_provider_dead", lambda *a, **k: False)
    monkeypatch.setattr(mr, "_breaker_scope", lambda *a: _async(""))
    monkeypatch.setattr(mr, "_ahm", None)

    async def fail_first(self, spec, *a, **k):
        seen.append(spec.provider)
        if spec.provider == "anthropic":
            raise RuntimeError("model not found")      # hard failure: the router would fall through to the next spec
        return "ok"
    monkeypatch.setattr(mr.ModelRouter, "_call_provider", fail_first)
    with pytest.raises(LLMUnavailable):
        await mr.ModelRouter().call(f"card {CARD}", org_id="o1", plan="starter")
    assert "openrouter" not in seen
    seen.clear()
    with pytest.raises(LLMUnavailable):                                   # explicit label, no pattern hit
        await mr.ModelRouter().call("plain text", org_id="o1", plan="starter", data_level="restricted")
    assert "openrouter" not in seen


async def test_call_openrouter_applies_the_policy_for_callers_that_skip_the_router(env, monkeypatch):
    """council and the context compressor call call_openrouter directly."""
    from aether_os.core.llm import openrouter_client as oc
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    with pytest.raises(LLMUnavailable):
        await oc.call_openrouter(f"card {CARD}", model="paid/model", api_key="k")
    with pytest.raises(LLMUnavailable):                                   # a :free model without the operator's opt-in
        await oc.call_openrouter("hello", model="meta-llama/llama-3.2-3b-instruct:free", api_key="k")
    monkeypatch.setattr(controls, "_flag", (1e18, True))                 # kill switch
    with pytest.raises(LLMUnavailable, match="kill switch"):
        await oc.call_openrouter("hello", model="paid/model", api_key="k")


async def test_platform_calls_have_a_budget_that_stops_them(env, monkeypatch):
    monkeypatch.setenv("PLATFORM_LLM_MONTHLY_CAP_USD", "1.0")
    assert (await guard.admit(None, None, "hi", None, 100)).plan == "platform"
    await budget.get_budget_manager().record_usage(PLATFORM_ORG, 0, int(1.5 / 15 * 1_000_000), model="claude-sonnet-4-6")
    with pytest.raises(LLMUnavailable, match="exhausted"):
        await guard.admit(None, None, "hi", None, 100)
    monkeypatch.setenv("PLATFORM_LLM_MONTHLY_CAP_USD", "abc")
    with pytest.raises(LLMUnavailable, match="not a number"):
        await guard.admit(None, None, "hi", None, 100)


async def test_router_records_platform_usage(env, monkeypatch):
    import asyncio

    async def provider(self, spec, *a, **k):
        return "x" * 4000
    monkeypatch.setattr(mr, "get_fallback_chain", lambda: [ModelSpec("anthropic", "claude-sonnet-4-6", 5, 1)])
    monkeypatch.setattr(mr.ModelRouter, "_call_provider", provider)
    monkeypatch.setattr(mr, "_provider_key", lambda *a: _async("k"))
    monkeypatch.setattr(mr, "_is_provider_dead", lambda *a, **k: False)
    monkeypatch.setattr(mr, "_breaker_scope", lambda *a: _async(""))
    await mr.ModelRouter().call("platform job", org_id=None)
    await asyncio.sleep(0.3)
    assert (await budget.get_budget_manager().get_usage(PLATFORM_ORG))["output_tokens"] > 0
