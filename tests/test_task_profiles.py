"""KAN-211: task type -> tier / max_tokens / timeout, truncation retries once then fails, org plan is authoritative."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from aether_os.core.errors import LLMTruncated
from aether_os.core.llm import controls, guard, task_profiles as tp
from aether_os.core.model_router_providers import ModelSpec


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LLM_MAX_TOKENS_HEAVY", "LLM_MAX_TOKENS_LIGHT", "LLM_TIMEOUT_HEAVY", "LLM_TIMEOUT_LIGHT",
                 "LLM_MAX_TOKENS_CEILING", "OPENROUTER_HEAVY_MODEL", "OPENROUTER_LIGHT_MODEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("task,tier", [
    ("architecture", "heavy"), ("code_generation", "heavy"), ("analysis", "heavy"),
    ("code_fix", "light"), ("classify", "light"), ("summarize", "light"), ("verify", "light"),
    ("syntax_check", "none"), ("test_result", "none"), ("never_heard_of_it", "heavy"),
])
def test_each_task_type_resolves_its_tier(task, tier):
    assert tp.profile_for(task).tier == tier


def test_limits_are_sized_for_reasoning_and_overridable(monkeypatch):
    heavy, light = tp.profile_for("code_generation"), tp.profile_for("code_fix")
    assert heavy.max_tokens >= 16000 and light.max_tokens >= 4000 and heavy.max_tokens > light.max_tokens
    assert heavy.timeout_s > light.timeout_s
    monkeypatch.setenv("LLM_MAX_TOKENS_LIGHT", "6000")
    monkeypatch.setenv("LLM_TIMEOUT_HEAVY", "bogus")
    assert tp.profile_for("code_fix").max_tokens == 6000
    assert tp.profile_for("code_generation").timeout_s == 240      # bad value falls back to the default


def test_explicit_limit_wins_and_tool_tasks_are_refused():
    assert tp.resolve_max_tokens("code_generation", 1234) == 1234
    assert tp.resolve_max_tokens("code_generation", None) == tp.profile_for("code_generation").max_tokens
    with pytest.raises(ValueError, match="tool"):
        tp.resolve_max_tokens("syntax_check", None)


def test_tier_model_goes_first_among_openrouter_entries(monkeypatch):
    chain = [ModelSpec("openrouter", "heavy/m", 60, 1), ModelSpec("ollama", "q", 60, 1)]
    assert tp.tiered_chain(chain, "code_fix") is chain          # no env model: unchanged
    monkeypatch.setenv("OPENROUTER_LIGHT_MODEL", "light/m")
    out = tp.tiered_chain(chain, "code_fix")
    assert [(s.provider, s.model) for s in out] == [("openrouter", "light/m"), ("openrouter", "heavy/m"), ("ollama", "q")]
    monkeypatch.setenv("OPENROUTER_HEAVY_MODEL", "heavy/m")
    assert tp.tiered_chain(chain, "architecture") is chain


def test_truncation_retries_once_with_a_larger_limit_then_succeeds():
    calls = []

    async def call(n):
        calls.append(n)
        if len(calls) == 1:
            raise LLMTruncated("cut")
        return "full file"
    assert asyncio.run(tp.call_with_growth(call, 1000, 5, "x")) == "full file"
    assert calls == [1000, 2000]


def test_truncation_twice_fails_with_a_reason_and_returns_no_text():
    calls = []

    async def call(n):
        calls.append(n)
        raise LLMTruncated("cut")
    with pytest.raises(LLMTruncated, match="truncated at max_tokens=1000 and again at 2000"):
        asyncio.run(tp.call_with_growth(call, 1000, 5, "x"))
    assert len(calls) == 2


def test_router_raises_truncation_without_falling_back_or_caching(monkeypatch):
    from aether_os.core import model_router as mr
    monkeypatch.setenv("PRIMARY_LLM", "ollama")
    router = mr.ModelRouter()
    seen = []

    async def fake(self, spec, prompt, task_type, system, max_tokens, api_key=None, timeout=None):
        seen.append(max_tokens)
        raise LLMTruncated("cut")
    with patch.object(mr.ModelRouter, "_call_provider", fake), \
         patch("aether_os.core.llm.guard.admit", new_callable=AsyncMock) as admit, \
         patch("aether_os.core.llm.cache.get_llm_cache") as cache:
        admit.return_value = guard.Admission("pro", "sonnet", [])
        cache.return_value.get = AsyncMock(return_value=None)
        cache.return_value.set = AsyncMock()
        with pytest.raises(LLMTruncated, match="again at"):
            asyncio.run(router.call("p", task_type="code_fix", enforce_local=True))
        cache.return_value.set.assert_not_called()
    limit = tp.profile_for("code_fix").max_tokens
    assert seen == [limit, limit * 2]                              # task type's limit, then one retry


def _policy(plan, cap=None):
    return controls.OrgPolicy(plan=plan, cap_usd=cap, disabled=False, deleted=False)


def test_intent_verification_call_uses_the_orgs_plan_not_the_callers(monkeypatch):
    """p01 intent_verification passed plan='trial' (run row default); the org is on pro (25M tokens)."""
    seen = {}

    async def check(self, org_id, plan, projected_cost_usd=0.0, cap_usd=None):
        seen["plan"], seen["cap"] = plan, cap_usd
        return True, "ok", "sonnet"
    monkeypatch.setattr(controls, "global_kill_active", AsyncMock(return_value=False))
    monkeypatch.setattr(controls, "org_policy", AsyncMock(return_value=_policy("pro")))
    monkeypatch.setattr("aether_os.core.llm.budget.TokenBudgetManager.check_budget", check)
    adm = asyncio.run(guard.admit("org_1", "trial", "hello", None, 100))
    assert adm.plan == "pro" and seen == {"plan": "pro", "cap": 200.0}


def test_unknown_org_plan_is_still_refused(monkeypatch):
    from aether_os.core.errors import LLMUnavailable
    monkeypatch.setattr(controls, "global_kill_active", AsyncMock(return_value=False))
    monkeypatch.setattr(controls, "org_policy", AsyncMock(return_value=_policy("")))
    with pytest.raises(LLMUnavailable):
        asyncio.run(guard.admit("org_1", "pro", "hello", None, 100))


def test_no_phase_hard_codes_max_tokens_on_a_model_call():
    """Limits come from the task type; a hard-coded number was a guess that truncated reasoning-model replies."""
    import pathlib
    import re
    root = pathlib.Path(__file__).parent.parent
    pattern = re.compile(r"\.call\([^\n]*max_tokens=\d+")
    bad = [f"{p.relative_to(root)}:{i}" for d in ("phases", "stages") for p in (root / d).rglob("*.py")
           if "templates" not in p.parts for i, line in enumerate(p.read_text().splitlines(), 1) if pattern.search(line)]
    assert bad == []


def test_documentation_is_light_but_gets_room_for_long_output():
    prof = tp.profile_for("documentation")
    assert prof.tier == "light" and prof.max_tokens == 12288
