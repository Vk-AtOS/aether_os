"""The OpenAI-compatible client can point at another provider (NVIDIA build.nvidia.com) by setting two variables."""
import asyncio
import importlib

import httpx

import aether_os.core.llm.controls as controls
import aether_os.core.llm.openrouter_client as orc


def test_base_url_defaults_to_openrouter_and_can_be_overridden(monkeypatch):
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    assert orc.base_url() == "https://openrouter.ai/api/v1"
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://integrate.api.nvidia.com/v1/")
    assert orc.base_url() == "https://integrate.api.nvidia.com/v1"


def test_call_goes_to_the_configured_endpoint(monkeypatch):
    seen = {}

    async def post(self, url, json=None, headers=None):
        seen["url"], seen["model"] = url, json["model"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setenv("ALLOW_COMMUNITY_LLM", "1")
    monkeypatch.setattr(httpx.AsyncClient, "post", post)

    async def no_kill():
        return False
    monkeypatch.setattr(controls, "global_kill_active", no_kill)
    out = asyncio.run(orc.call_openrouter("hi", task_type="review", model="nvidia/nemotron-3-ultra-550b-a55b",
                                          api_key="nvapi-test"))
    assert out == "ok"
    assert seen == {"url": "https://integrate.api.nvidia.com/v1/chat/completions",
                    "model": "nvidia/nemotron-3-ultra-550b-a55b"}


def test_council_models_can_be_replaced(monkeypatch):
    monkeypatch.setenv("OPENROUTER_COUNCIL_MODELS", "nvidia/a, nvidia/b")
    try:
        assert importlib.reload(orc).COUNCIL_MODELS == ["nvidia/a", "nvidia/b"]
    finally:
        monkeypatch.delenv("OPENROUTER_COUNCIL_MODELS")
        importlib.reload(orc)


def _fake_post(monkeypatch, response_json, seen):
    async def post(self, url, json=None, headers=None):
        seen.update(json)
        return httpx.Response(200, json=response_json, request=httpx.Request("POST", url))

    async def no_kill():
        return False
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(controls, "global_kill_active", no_kill)
    monkeypatch.setenv("ALLOW_COMMUNITY_LLM", "1")


def test_extra_body_is_merged_but_never_overrides_the_call(monkeypatch):
    seen = {}
    _fake_post(monkeypatch, {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}, seen)
    monkeypatch.setenv("OPENROUTER_EXTRA_BODY", '{"chat_template_kwargs": {"enable_thinking": false}, "max_tokens": 1}')
    asyncio.run(orc.call_openrouter("hi", model="m", max_tokens=512, api_key="k"))
    assert seen["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["max_tokens"] == 512 and seen["model"] == "m"


def test_bad_extra_body_is_ignored(monkeypatch):
    monkeypatch.setenv("OPENROUTER_EXTRA_BODY", "not json")
    assert orc.extra_body() == {}
    monkeypatch.setenv("OPENROUTER_EXTRA_BODY", "[1]")
    assert orc.extra_body() == {}


def test_a_truncated_reply_is_an_error_not_an_answer(monkeypatch):
    # Regression (AWS testbed, 21 Nov 2026): a council verdict cut off mid-JSON was returned as the answer, the parse
    # failed, and strict mode rejected a request the model had approved.
    import pytest
    _fake_post(monkeypatch, {"choices": [{"message": {"content": '{"passed": true, "sugg'}, "finish_reason": "length"}]}, {})
    with pytest.raises(RuntimeError, match="truncated at max_tokens=512"):
        asyncio.run(orc.call_openrouter("hi", model="m", max_tokens=512, api_key="k"))
