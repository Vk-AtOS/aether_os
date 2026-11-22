"""The install's OpenAI-compatible endpoint can provide embeddings (KAN-219: production returned zero vectors)."""
from __future__ import annotations

import asyncio

import pytest

from aether_os.core.llm import embeddings_openai as eo


class _Resp:
    def __init__(self, data, code=200):
        self._data, self.status_code = data, code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


def _fake_httpx(monkeypatch, resp, seen):
    import httpx

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            seen.update(url=url, json=json, headers=headers)
            return resp
    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def test_not_configured_means_no_call(monkeypatch):
    monkeypatch.delenv("EMBEDDING_OPENAI_MODEL", raising=False)
    assert not eo.configured() and asyncio.run(eo.embed("x")) is None


def test_endpoint_embedding_with_input_type(monkeypatch):
    monkeypatch.setenv("EMBEDDING_OPENAI_MODEL", "nvidia/nv-embedqa-e5-v5")
    monkeypatch.setenv("EMBEDDING_INPUT_TYPE", "passage")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://example.test/v1")
    seen: dict = {}
    _fake_httpx(monkeypatch, _Resp({"data": [{"embedding": [0.1, 0.2]}]}), seen)
    assert asyncio.run(eo.embed("hello")) == [0.1, 0.2]
    assert seen["url"] == "https://example.test/v1/embeddings"
    assert seen["json"]["input_type"] == "passage" and seen["json"]["input"] == ["hello"]
    assert seen["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.parametrize("resp", [_Resp({}, 500), _Resp({"data": []}), _Resp({"data": [{"embedding": []}]})])
def test_failures_return_none_so_the_caller_falls_back(monkeypatch, resp):
    monkeypatch.setenv("EMBEDDING_OPENAI_MODEL", "m")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    _fake_httpx(monkeypatch, resp, {})
    assert asyncio.run(eo.embed("x")) is None
