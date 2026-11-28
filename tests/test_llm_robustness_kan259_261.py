"""KAN-259 reasoning-model truncation, KAN-260 unreachable providers, KAN-261 token/money budget and the p01 cache loop."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

import aether_os.core.db as db
from aether_os.core import model_router as mr
from aether_os.core.errors import LLMTruncated, LLMUnavailable
from aether_os.core.llm import budget, controls, guard, openrouter_client as oc, task_profiles as tp
from aether_os.core.llm import plans, provider_probe
from aether_os.core.model_router_providers import ModelSpec
from aether_os.core.models import Organisation


# ── KAN-259 ─────────────────────────────────────────────────────────────────

class FakeOpenRouter:
    """Stands in for httpx.AsyncClient: a reasoning model that spends a small limit thinking, a big one answering."""
    def __init__(self, answer_needs=3000):
        self.payloads, self.answer_needs = [], answer_needs

    def client(self, *a, **k):
        fake = self

        class C:
            async def __aenter__(self): return self
            async def __aexit__(self, *e): return False

            async def post(self, url, json=None, headers=None):
                fake.payloads.append(json)
                limit, off = json["max_tokens"], json.get("reasoning") == {"enabled": False}
                resp = MagicMock()
                resp.raise_for_status = lambda: None
                if limit >= fake.answer_needs or off:
                    body = {"choices": [{"finish_reason": "stop", "message": {"content": "answer"}}], "usage": {}}
                else:   # all tokens went on reasoning: finish_reason stop, content empty
                    body = {"choices": [{"finish_reason": None, "message": {"content": "", "reasoning": "thinking..."}}],
                            "usage": {"completion_tokens_details": {"reasoning_tokens": limit}}}
                resp.json = lambda: body
                return resp
        return C()


@pytest.fixture
def or_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("ALLOW_COMMUNITY_LLM", "1")
    monkeypatch.delenv("OPENROUTER_EXTRA_BODY", raising=False)
    monkeypatch.setattr("aether_os.core.llm.controls.global_kill_active", AsyncMock(return_value=False))


def test_empty_content_with_reasoning_tokens_counts_as_truncated():
    assert tp.is_truncated({"finish_reason": "length", "message": {"content": "partial"}}, None)
    assert tp.is_truncated({"finish_reason": "stop", "message": {"content": ""}}, {"completion_tokens_details": {"reasoning_tokens": 900}})
    assert tp.is_truncated({"message": {"content": None, "reasoning": "x"}}, None)
    assert not tp.is_truncated({"finish_reason": "stop", "message": {"content": "ok"}}, {"completion_tokens_details": {"reasoning_tokens": 900}})
    assert not tp.is_truncated({"finish_reason": "stop", "message": {"content": ""}}, {})   # empty without reasoning: not ours


def test_small_explicit_limit_is_raised_to_the_reasoning_floor_and_answer_returns(or_env):
    fake = FakeOpenRouter(answer_needs=3000)
    with patch("httpx.AsyncClient", fake.client):
        out = asyncio.run(oc.call_openrouter("p", "ui_component", max_tokens=2000, model="m/x", api_key="k"))
    assert out == "answer" and fake.payloads[0]["max_tokens"] == tp.reasoning_floor()


def test_reasoning_cut_off_retries_once_larger_with_reasoning_off(or_env, monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS_FLOOR", "100")
    fake = FakeOpenRouter(answer_needs=10 ** 9)          # only reasoning-off can answer
    with patch("httpx.AsyncClient", fake.client):
        out = asyncio.run(tp.call_with_growth(
            lambda n: oc.call_openrouter("p", "ui_component", max_tokens=n, model="m/x", api_key="k"), 2000, 5, "x"))
    assert out == "answer"
    assert [p["max_tokens"] for p in fake.payloads] == [2000, 4000]
    assert "reasoning" not in fake.payloads[0] and fake.payloads[1]["reasoning"] == {"enabled": False}
    assert tp.retry_without_reasoning.get() is False      # the switch does not leak into the next call


def test_both_attempts_cut_off_still_fails_with_a_reason(or_env, monkeypatch):
    fake = FakeOpenRouter(answer_needs=10 ** 9)
    fake.client  # noqa: B018
    orig = fake.client

    def never_answers(*a, **k):
        c = orig()
        post = c.post

        async def p(url, json=None, headers=None):
            json = {**json}
            json.pop("reasoning", None)    # a provider that ignores the switch
            return await post(url, json=json, headers=headers)
        c.post = p
        return c
    with patch("httpx.AsyncClient", never_answers), pytest.raises(LLMTruncated, match="again at"):
        asyncio.run(tp.call_with_growth(
            lambda n: oc.call_openrouter("p", "ui_component", max_tokens=n, model="m/x", api_key="k"), 2000, 5, "x"))


# ── KAN-260 ─────────────────────────────────────────────────────────────────

@pytest.mark.ollama_probe
def test_probe_says_why_ollama_cannot_serve(monkeypatch):
    provider_probe._CACHE.clear()
    monkeypatch.setattr(provider_probe, "_base_url", lambda: "http://ollama.test")

    class Down:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *e): return False
        async def get(self, url): raise ConnectionError("All connection attempts failed")
    with patch("httpx.AsyncClient", Down):
        reason = asyncio.run(provider_probe.ollama_model_unavailable("qwen2.5-coder:3b"))
    assert "not reachable" in reason and "All connection attempts failed" in reason

    provider_probe._CACHE.clear()

    class Up(Down):
        async def get(self, url):
            r = MagicMock(status_code=200)
            r.json = lambda: {"models": [{"name": "llama3:8b"}]}
            return r
    with patch("httpx.AsyncClient", Up):
        assert "not pulled" in asyncio.run(provider_probe.ollama_model_unavailable("qwen2.5-coder:3b"))
        assert asyncio.run(provider_probe.ollama_model_unavailable("llama3:8b")) == ""
    provider_probe._CACHE.clear()


@pytest.mark.ollama_probe
def test_exhausted_chain_lists_every_provider_and_why(monkeypatch):
    chain = [ModelSpec("openrouter", "a/b:free", 5, 1), ModelSpec("anthropic", "claude", 5, 1), ModelSpec("ollama", "qwen2.5-coder:3b", 5, 1)]
    monkeypatch.setattr(mr, "get_fallback_chain", lambda: chain)
    monkeypatch.setattr(mr, "_provider_key", AsyncMock(side_effect=lambda p, o: "k" if p == "openrouter" else None))
    monkeypatch.setattr(mr, "_breaker_scope", AsyncMock(return_value=""))
    monkeypatch.setattr(mr, "_is_provider_dead", lambda *a, **k: False)
    monkeypatch.setattr(mr, "_is_provider_configured", lambda spec: spec.provider != "anthropic")
    monkeypatch.setattr(mr, "ollama_model_unavailable", AsyncMock(return_value="Ollama at http://x is not reachable (ConnectError)"))
    monkeypatch.setenv("ALLOW_COMMUNITY_LLM", "1")

    async def boom(self, spec, *a, **k):
        raise RuntimeError("OpenRouter a/b:free HTTP 500: boom")
    with patch.object(mr.ModelRouter, "_call_provider", boom), \
         patch("aether_os.core.llm.guard.admit", AsyncMock(return_value=guard.Admission("pro", "sonnet", []))), \
         patch("aether_os.core.llm.cache.get_llm_cache") as cache:
        cache.return_value.get = AsyncMock(return_value=None)
        with pytest.raises(LLMUnavailable) as e:
            asyncio.run(mr.ModelRouter().call("p", task_type="code_fix"))
    msg = str(e.value)
    assert "openrouter/a/b:free" in msg and "HTTP 500" in msg                       # tried, why it failed
    assert "anthropic/claude: skipped, not configured" in msg                        # never configured
    assert "ollama/qwen2.5-coder:3b: skipped" in msg and "not reachable" in msg       # probed away, not "tried"
    assert "1 tried, 2 skipped" in msg


# ── KAN-261 ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def dbenv(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/b.db")
    monkeypatch.delenv("LLM_PLAN_TOKEN_CAPS", raising=False)
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    monkeypatch.setattr(controls, "_orgs", {})
    monkeypatch.setattr(budget, "_alerted", set())
    async with db.get_engine().begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    async with db.get_session_factory()() as s:
        s.add(Organisation(id="o1", name="O", slug="o", plan="pro"))
        await s.commit()
    yield
    await db.get_engine().dispose()


def test_default_token_caps_fit_many_real_builds():
    heaviest_build = 172_000
    assert plans.PLAN_LIMITS["trial"].tokens // heaviest_build >= 10
    assert plans.PLAN_LIMITS["free"].tokens // heaviest_build >= 5


def test_token_cap_precedence_org_then_env_then_plan(monkeypatch):
    monkeypatch.delenv("LLM_PLAN_TOKEN_CAPS", raising=False)
    assert plans.token_cap_for("pro") == plans.PLAN_LIMITS["pro"].tokens
    monkeypatch.setenv("LLM_PLAN_TOKEN_CAPS", '{"pro": 123}')
    assert plans.token_cap_for("pro") == 123 and plans.token_cap_for("trial") == plans.PLAN_LIMITS["trial"].tokens
    assert plans.token_cap_for("pro", 777) == 777
    monkeypatch.setenv("LLM_PLAN_TOKEN_CAPS", "garbage")
    assert plans.token_cap_for("pro") == plans.PLAN_LIMITS["pro"].tokens


@pytest.mark.asyncio
async def test_free_model_token_stop_says_tokens_not_money(dbenv):
    mgr = budget.get_budget_manager()
    await mgr.record_usage("o1", 0, 600_000, model="minimax/minimax-m2.5:free")
    ok, _, _ = await mgr.check_budget("o1", "pro", token_cap=500_000)
    assert not ok
    ok, reason, _ = await mgr.check_budget("o1", "pro", token_cap=500_000)
    assert "TOKEN limit" in reason and "600,000 of 500,000 tokens" in reason and "$0.00" in reason and "not the limit" in reason
    ok, _, _ = await mgr.check_budget("o1", "pro")                  # plan default (25M) leaves room: the limit is not removed, it is sized
    assert ok


@pytest.mark.asyncio
async def test_spend_stop_says_spend_and_both_limits_still_apply(dbenv):
    mgr = budget.get_budget_manager()
    await mgr.record_usage("o1", 0, 100_000, model="claude-sonnet-4-6")      # $1.50
    ok, reason, _ = await mgr.check_budget("o1", "pro", cap_usd=1.0)
    assert not ok and "SPEND limit" in reason and "$1.50 of $1.00" in reason


@pytest.mark.asyncio
async def test_org_token_cap_reaches_the_budget_check(dbenv, monkeypatch):
    async with db.get_session_factory()() as s:
        o = await s.get(Organisation, "o1")
        o.llm_monthly_token_cap = 1000
        await s.commit()
    monkeypatch.setattr(controls, "global_kill_active", AsyncMock(return_value=False))
    await budget.get_budget_manager().record_usage("o1", 0, 5000, model="x:free")
    with pytest.raises(LLMUnavailable, match="TOKEN limit.*5,000 of 1,000"):
        await guard.admit("o1", "pro", "hello", None, 100)


# ── KAN-261 G9: p01 analysis failed in ~50 ms ───────────────────────────────

def _router_run(monkeypatch, replies, refresh=False, cache_get=None):
    chain = [ModelSpec("anthropic", "claude-sonnet-4-6", 5, 2)]
    monkeypatch.setattr(mr, "get_fallback_chain", lambda: chain)
    monkeypatch.setattr(mr, "_provider_key", AsyncMock(return_value="k"))
    monkeypatch.setattr(mr, "_breaker_scope", AsyncMock(return_value=""))
    monkeypatch.setattr(mr, "_is_provider_dead", lambda *a, **k: False)
    it = iter(replies)

    async def provider(self, *a, **k):
        return next(it)
    sets = []

    async def get(*a, **k):
        return cache_get

    async def set_(*a, **k):
        sets.append(k)
    with patch.object(mr.ModelRouter, "_call_provider", provider), \
         patch("aether_os.core.llm.guard.admit", AsyncMock(return_value=guard.Admission("pro", "sonnet", []))), \
         patch("aether_os.core.llm.cache.get_llm_cache") as cache:
        cache.return_value.get, cache.return_value.set = get, set_

        async def go():
            r = await mr.ModelRouter().call("p", task_type="analysis", org_id="o1", refresh_cache=refresh)
            await asyncio.sleep(0.05)
            return r
        return asyncio.run(go()), sets


def test_placeholder_reply_is_never_cached(monkeypatch):
    """The cache write used to run BEFORE the placeholder guard: the stub was served again to every retry and later run."""
    (text, _), sets = _router_run(monkeypatch, ["...", '{"ok": 1}'])
    assert text == '{"ok": 1}' and len(sets) == 1       # only the good reply was stored


def test_refresh_bypasses_the_cached_reply_and_replaces_it(monkeypatch):
    (text, provider), sets = _router_run(monkeypatch, ['{"fresh": 1}'], refresh=True, cache_get="bad cached text")
    assert text == '{"fresh": 1}' and provider == "anthropic" and sets[0]["replace"] is True


def test_call_json_retry_does_not_get_the_same_cached_bad_reply(monkeypatch):
    from aether_os.core.llm.client import LLMClient
    client = LLMClient()
    seen = []

    async def call(prompt, **kw):
        seen.append(kw.get("refresh_cache"))
        return "not json" if len(seen) == 1 else '{"intake": {}}'
    monkeypatch.setattr(client, "call", call)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    out = asyncio.run(client.call_json("p", task_type="analysis", org_id="o1", run_id="r1", phase="p01"))
    assert out == {"intake": {}} and seen == [False, True]
