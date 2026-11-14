"""An organisation's provider key is used for that organisation's calls only.

Real code path: save_api_key → (SQLite) org_api_keys → ModelRouter.call →
_call_provider → provider adapter → SDK client constructor. Only the vendor SDK /
HTTP client (the network boundary) is replaced, by a fake that records the key
it was given.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

import aether_os.core.db as db
import aether_os.core.model_router as router_mod
from aether_os.core import api_key_store
from aether_os.core.errors import LLMUnavailable
from aether_os.core.llm import client as llm_client
from aether_os.core.llm._org_context import _current_org_id
from aether_os.core.llm.ahm import default_ahm

pytestmark = pytest.mark.asyncio
anthropic = pytest.importorskip("anthropic")

ORG_A, ORG_B = "org-a", "org-b"
KEY_A, KEY_B, PLATFORM = "sk-ant-org-a-key", "sk-ant-org-b-key", "sk-ant-platform-key"


class FakeAnthropic:
    """Stands in for anthropic.AsyncAnthropic: records which key served which prompt."""
    calls: list = []

    def __init__(self, api_key=None, **_kwargs):
        self.api_key = api_key
        self.messages = self

    async def create(self, messages, **_kwargs):
        await asyncio.sleep(0)  # let concurrent calls interleave
        FakeAnthropic.calls.append((self.api_key, messages[0]["content"]))
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                               content=[SimpleNamespace(text="fine")])


class FakeHttpx:
    """Stands in for httpx.AsyncClient inside call_openrouter."""
    auth_headers: list = []

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, _url, json=None, headers=None):
        FakeHttpx.auth_headers.append(headers["Authorization"])
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"choices": [{"message": {"content": "fine"}}]})


@pytest_asyncio.fixture
async def keys(tmp_path, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "GOOGLE_API_KEY",
                "OPENROUTER_API_KEY", "OPENROUTER_FALLBACK_MODELS", "OPENROUTER_HEAVY_MODEL",
                "BEDROCK_ENABLED", "AWS_ACCESS_KEY_ID", "OFFLINE_MODE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PRIMARY_LLM", "anthropic")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/keys.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeAnthropic)
    monkeypatch.setattr("httpx.AsyncClient", FakeHttpx)

    async def _no_ollama(*_a, **_k):   # never call a real local model from a test
        raise RuntimeError("ollama not running")
    monkeypatch.setattr(llm_client, "_call_ollama_with_model", _no_ollama)

    FakeAnthropic.calls, FakeHttpx.auth_headers = [], []
    api_key_store._cache.clear()
    router_mod._DEAD_PROVIDERS.clear()
    router_mod._DEAD_MODELS.clear()
    default_ahm.reset()
    token = _current_org_id.set(None)
    yield
    _current_org_id.reset(token)
    await asyncio.gather(*list(router_mod._background_tasks), return_exceptions=True)
    api_key_store._cache.clear()
    default_ahm.reset()
    await engine.dispose()


def _prompt(tag: str) -> str:
    return f"{tag} {uuid.uuid4().hex}"   # unique, so the semantic cache never answers


async def _call(org_id, tag="hello"):
    return await router_mod.ModelRouter().call(_prompt(tag), task_type="summarize", org_id=org_id, plan="starter")


async def test_saving_an_org_key_never_touches_the_process_environment(keys):
    before = dict(os.environ)
    for provider, key in (("anthropic", KEY_A), ("google", "google-org-a-key"), ("openrouter", "or-org-a-key")):
        await api_key_store.save_api_key(provider, ORG_A, key, user_id="u1")
    assert dict(os.environ) == before
    assert not any("org-a-key" in v for v in os.environ.values())
    assert await api_key_store.get_api_key("anthropic", ORG_A) == KEY_A
    assert await api_key_store.get_api_key("anthropic", ORG_B) is None


async def test_org_b_call_uses_platform_key_not_org_a_key(keys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", PLATFORM)
    await api_key_store.save_api_key("anthropic", ORG_A, KEY_A)

    assert (await _call(ORG_A))[1] == "anthropic"
    assert (await _call(ORG_B))[1] == "anthropic"
    assert (await _call(None))[1] == "anthropic"

    assert [k for k, _ in FakeAnthropic.calls] == [KEY_A, PLATFORM, PLATFORM]


async def test_without_a_platform_key_org_b_gets_no_anthropic_at_all(keys):
    await api_key_store.save_api_key("anthropic", ORG_A, KEY_A)
    await _call(ORG_A)
    assert FakeAnthropic.calls[-1][0] == KEY_A

    served_before = len(FakeAnthropic.calls)
    with pytest.raises(LLMUnavailable):
        await _call(ORG_B)
    assert len(FakeAnthropic.calls) == served_before   # org A's key did not serve org B
    assert os.environ.get("ANTHROPIC_API_KEY") is None


async def test_concurrent_calls_each_get_their_own_orgs_key(keys):
    await api_key_store.save_api_key("anthropic", ORG_A, KEY_A)
    await api_key_store.save_api_key("anthropic", ORG_B, KEY_B)

    await asyncio.gather(*(_call(org, tag=org) for org in [ORG_A, ORG_B] * 8))

    assert len(FakeAnthropic.calls) == 16
    for key, prompt in FakeAnthropic.calls:
        assert key == (KEY_A if prompt.startswith(ORG_A) else KEY_B)


async def test_org_key_still_used_after_the_lookup_cache_expires(keys):
    """Previously the key was read from a 60 s cache only; once it expired the call
    fell back to the process environment (whichever org had saved last)."""
    await api_key_store.save_api_key("anthropic", ORG_A, KEY_A)
    await _call(ORG_A)
    api_key_store._cache.clear()   # what TTL expiry does
    await _call(ORG_A)
    assert [k for k, _ in FakeAnthropic.calls] == [KEY_A, KEY_A]


async def test_updated_key_takes_effect_on_the_next_call(keys):
    await api_key_store.save_api_key("anthropic", ORG_A, "sk-ant-old-key")
    await _call(ORG_A)
    await api_key_store.save_api_key("anthropic", ORG_A, KEY_A)
    await _call(ORG_A)
    assert [k for k, _ in FakeAnthropic.calls] == ["sk-ant-old-key", KEY_A]


async def test_context_org_is_used_when_the_caller_passes_no_org_id(keys):
    await api_key_store.save_api_key("anthropic", ORG_A, KEY_A)
    llm_client.set_org_context(ORG_A)
    await _call(None)
    assert FakeAnthropic.calls[-1][0] == KEY_A


async def test_openrouter_key_is_per_org_too(keys, monkeypatch):
    monkeypatch.setenv("PRIMARY_LLM", "openrouter")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODELS", "test/model:free")
    await api_key_store.save_api_key("openrouter", ORG_A, "or-org-a-key")

    assert (await _call(ORG_A))[1] == "openrouter"
    assert FakeHttpx.auth_headers == ["Bearer or-org-a-key"]

    with pytest.raises(LLMUnavailable):
        await _call(ORG_B)
    assert FakeHttpx.auth_headers == ["Bearer or-org-a-key"]   # nothing sent for org B
