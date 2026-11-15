"""The router's circuit breaker is per organisation and expires; the council reviewers
resolve provider keys per call and per org.

Same approach (and fixture) as test_org_api_key_isolation: the real router, key store
and council code run against SQLite; only the vendor SDK / HTTP client is replaced.
"""
from __future__ import annotations

import os
import sys
import time
import types
from types import SimpleNamespace

import pytest

import aether_os.core.model_router_providers as providers_mod
from aether_os.core import api_key_store
from aether_os.core.council import council, council_reviewer
from aether_os.core.errors import LLMUnavailable
from aether_os.core.llm._org_context import _current_org_id
from aether_os.tests.test_org_api_key_isolation import (  # noqa: F401  (keys is a fixture)
    KEY_A, ORG_A, ORG_B, PLATFORM, FakeAnthropic, FakeHttpx, _call, keys,
)

pytestmark = pytest.mark.asyncio
anthropic = pytest.importorskip("anthropic")

BAD_KEYS: set = set()


class RejectingAnthropic(FakeAnthropic):
    """FakeAnthropic that rejects the keys in BAD_KEYS the way the vendor does."""

    async def create(self, messages, **kwargs):
        if self.api_key in BAD_KEYS:
            FakeAnthropic.calls.append((self.api_key, "rejected"))
            raise RuntimeError("401 authentication_error: invalid_api_key")
        return await super().create(messages, **kwargs)


@pytest.fixture
def rejecting(keys, monkeypatch):
    BAD_KEYS.clear()
    monkeypatch.setattr(anthropic, "AsyncAnthropic", RejectingAnthropic)
    yield BAD_KEYS
    BAD_KEYS.clear()


def _keys_used():
    return [k for k, _ in FakeAnthropic.calls]


# ── 6. Circuit breaker scope and expiry ───────────────────────────────────────

async def test_one_orgs_bad_key_does_not_disable_the_provider_for_other_orgs(rejecting, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", PLATFORM)
    await api_key_store.save_api_key("anthropic", ORG_A, KEY_A)
    rejecting.add(KEY_A)

    with pytest.raises(LLMUnavailable):
        await _call(ORG_A)

    assert (await _call(ORG_B))[1] == "anthropic"      # was: LLMUnavailable for everyone
    assert (await _call(None))[1] == "anthropic"
    assert _keys_used()[-2:] == [PLATFORM, PLATFORM]
    assert (ORG_A, "anthropic") in providers_mod._DEAD_PROVIDERS

    # Org A's breaker is open: its key is not tried again while the entry is live.
    tried = len(FakeAnthropic.calls)
    with pytest.raises(LLMUnavailable):
        await _call(ORG_A)
    assert len(FakeAnthropic.calls) == tried


async def test_breaker_expires_so_a_fixed_key_recovers(rejecting, monkeypatch):
    await api_key_store.save_api_key("anthropic", ORG_A, KEY_A)
    rejecting.add(KEY_A)
    with pytest.raises(LLMUnavailable):
        await _call(ORG_A)
    rejecting.clear()   # the org fixes its key / account

    opened_until = providers_mod._DEAD_PROVIDERS[(ORG_A, "anthropic")]
    assert 0 < opened_until - time.monotonic() <= providers_mod._dead_ttl()
    with pytest.raises(LLMUnavailable):
        await _call(ORG_A)                               # still open

    providers_mod._DEAD_PROVIDERS[(ORG_A, "anthropic")] = time.monotonic() - 1   # TTL elapsed
    assert (await _call(ORG_A))[1] == "anthropic"
    assert (ORG_A, "anthropic") not in providers_mod._DEAD_PROVIDERS


async def test_platform_key_failure_is_platform_wide_but_spares_orgs_with_their_own_key(rejecting, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", PLATFORM)
    await api_key_store.save_api_key("anthropic", ORG_A, KEY_A)
    rejecting.add(PLATFORM)

    with pytest.raises(LLMUnavailable):
        await _call(ORG_B)
    assert (providers_mod.PLATFORM_SCOPE, "anthropic") in providers_mod._DEAD_PROVIDERS

    tried = len(FakeAnthropic.calls)
    with pytest.raises(LLMUnavailable):
        await _call("org-c")                             # also on the platform key: skipped
    assert len(FakeAnthropic.calls) == tried

    assert (await _call(ORG_A))[1] == "anthropic"        # own key, own breaker
    assert _keys_used()[-1] == KEY_A


async def test_model_specific_breaker_is_scoped_too():
    providers_mod._DEAD_MODELS.clear()
    providers_mod._mark_provider_dead(
        "openrouter", RuntimeError("model x is not available for this account"), model="x", scope=ORG_A)
    assert providers_mod._is_provider_dead("openrouter", "x", ORG_A)
    assert not providers_mod._is_provider_dead("openrouter", "x", ORG_B)
    assert not providers_mod._is_provider_dead("openrouter", "x")   # platform scope
    providers_mod._DEAD_MODELS.clear()


# ── 7. Council reviewers resolve keys per call, per org ───────────────────────

@pytest.fixture
def fake_genai(monkeypatch):
    used: list = []

    class Client:
        def __init__(self, api_key=None):
            used.append(api_key)
            self.models = self

        def generate_content(self, model, contents):
            return SimpleNamespace(text="SCORE: 7\nISSUES:\n- no pagination\nSTRENGTHS:\n- typed models")

    genai = types.ModuleType("google.genai")
    genai.Client = Client
    google = types.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    return used


async def test_council_gemini_and_claude_use_the_orgs_stored_keys(keys, fake_genai):
    await api_key_store.save_api_key("google", ORG_A, "google-org-a-key")
    await api_key_store.save_api_key("anthropic", ORG_A, KEY_A)
    before = dict(os.environ)

    report = await council_reviewer.run_council("def main(): pass", "run-1", org_id=ORG_A)

    assert sorted(r.model for r in report.reviews) == ["claude", "gemini"]   # was: no reviews
    assert fake_genai == ["google-org-a-key"] and _keys_used() == [KEY_A]
    assert dict(os.environ) == before

    # Another org has no keys and there is no platform key: it gets no review at all.
    assert await council_reviewer._call_gemini("x", "general", ORG_B) is None
    assert await council_reviewer._call_claude("x", "general", ORG_B) is None
    assert fake_genai == ["google-org-a-key"] and _keys_used() == [KEY_A]


async def test_council_uses_the_active_runs_org_when_none_is_passed(keys, fake_genai):
    await api_key_store.save_api_key("google", ORG_A, "google-org-a-key")
    _current_org_id.set(ORG_A)   # what init_org_llm_context does at the start of a run
    review = await council_reviewer._call_gemini("def main(): pass", "general")
    assert review is not None and review.model == "gemini"
    assert fake_genai == ["google-org-a-key"]


async def test_frontend_audit_council_sees_an_org_only_openrouter_key(keys):
    await api_key_store.save_api_key("openrouter", ORG_A, "or-org-a-key")
    _current_org_id.set(ORG_A)
    await council.FrontendAuditCouncil().audit("export default function App() { return null }")
    # was: OPENROUTER_API_KEY absent from the environment → OpenRouter skipped entirely
    assert FakeHttpx.auth_headers and set(FakeHttpx.auth_headers) == {"Bearer or-org-a-key"}
