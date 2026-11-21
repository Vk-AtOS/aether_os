"""KAN-207: POST /factory/start refuses a run (503 + Retry-After, nothing created) when no model provider in the chain is
usable, admits it as before when one is, and leaves the SQS queuing path unchanged.

Real gateway on a throwaway SQLite database (conftest `gw`); get_factory is replaced so no build ever runs. The Ollama
probe is replaced per test, except in the probe tests, which use a port nothing listens on: no network call leaves the host.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aether_os.core import model_admission
from aether_os.core.model_router_providers import PLATFORM_SCOPE, _DEAD_PROVIDERS
from aether_os.core.queue import sqs_client

pytestmark = pytest.mark.model_admission

NO_BUILD = AssertionError("a run was started without a usable model provider")
_PROVIDER_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GOOGLE_API_KEY", "OPENROUTER_API_KEY",
                 "OPENROUTER_FALLBACK_MODELS", "OPENROUTER_HEAVY_MODEL", "AWS_ACCESS_KEY_ID", "OFFLINE_MODE",
                 "SQS_QUEUE_URL")


@pytest.fixture
def no_provider(monkeypatch):
    """Bedrock primary but disabled, no third-party key, Ollama unreachable, no queue."""
    for k in _PROVIDER_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PRIMARY_LLM", "bedrock")
    monkeypatch.setenv("BEDROCK_ENABLED", "false")
    monkeypatch.setattr(sqs_client, "QUEUE_URL", "")
    monkeypatch.setattr(model_admission, "ollama_reachable", AsyncMock(return_value=False))
    monkeypatch.setattr(model_admission, "_OLLAMA_PROBE_CACHE", {})


def _runs(gw, org_id):
    return gw.sql("SELECT count(*) FROM runs WHERE org_id = ?", (org_id,))[0][0]


def _trial_used(gw, org_id):
    return gw.sql("SELECT trial_runs_used FROM organisations WHERE id = ?", (org_id,))[0][0]


def _start(gw, who, factory=None):
    with patch("aether_os.orchestrator.factory_pipeline.get_factory",
               **({"return_value": factory} if factory else {"side_effect": NO_BUILD})):
        return gw.client.post("/factory/start", headers=who.auth, json={"raw_input": "build a todo app"})


def test_no_usable_provider_is_refused_with_503_and_nothing_is_created(gw, no_provider):
    owner = gw.register("nomodel")
    runs, used = _runs(gw, owner.org_id), _trial_used(gw, owner.org_id)
    resp = _start(gw, owner)
    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"]["error"] == "no_model_provider"
    assert "no model provider available" in resp.json()["detail"]["message"]
    assert int(resp.headers["Retry-After"]) == 60
    assert _runs(gw, owner.org_id) == runs
    assert _trial_used(gw, owner.org_id) == used
    model_admission.ollama_reachable.assert_awaited()


def test_every_breaker_open_is_refused_until_the_first_one_closes(gw, no_provider, monkeypatch):
    owner = gw.register("breakeropen")
    monkeypatch.setenv("PRIMARY_LLM", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setitem(_DEAD_PROVIDERS, (PLATFORM_SCOPE, "anthropic"), time.monotonic() + 25)
    runs = _runs(gw, owner.org_id)
    resp = _start(gw, owner)
    assert resp.status_code == 503, resp.text
    assert "circuit breaker" in resp.json()["detail"]["message"]
    assert 1 <= int(resp.headers["Retry-After"]) <= 25
    assert _runs(gw, owner.org_id) == runs


def test_a_configured_provider_is_admitted_as_before_without_probing_anything(gw, no_provider, monkeypatch):
    owner = gw.register("hasmodel")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("PRIMARY_LLM", "anthropic")
    fake = MagicMock()
    fake.run = AsyncMock(return_value={})
    runs = _runs(gw, owner.org_id)
    resp = _start(gw, owner, factory=fake)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "started"
    assert _runs(gw, owner.org_id) == runs + 1
    model_admission.ollama_reachable.assert_not_awaited()   # an earlier provider was usable: Ollama is never probed


def test_reachable_ollama_counts_as_a_provider(gw, no_provider, monkeypatch):
    owner = gw.register("ollamaup")
    monkeypatch.setattr(model_admission, "ollama_reachable", AsyncMock(return_value=True))
    fake = MagicMock()
    fake.run = AsyncMock(return_value={})
    assert _start(gw, owner, factory=fake).status_code == 200


def test_queue_configured_queues_as_before_without_the_check(gw, no_provider, monkeypatch):
    owner = gw.register("queued")
    monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.example.invalid/123/jobs")
    check = AsyncMock(side_effect=AssertionError("the model check ran on the queuing path"))
    monkeypatch.setattr(model_admission, "check_model_admission", check)
    send = MagicMock(return_value=True)
    fake = MagicMock()
    fake.run = AsyncMock(side_effect=AssertionError("a queued run was also started in-process"))
    with patch("aether_os.core.queue.sqs_client.send_pipeline_job", send):
        resp = _start(gw, owner, factory=fake)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"
    assert send.call_count == 1
    fake.run.assert_not_called()
    assert gw.sql("SELECT status FROM runs WHERE id = ?", (resp.json()["run_id"],))[0][0] == "queued"


@pytest.mark.asyncio
async def test_ollama_probe_is_short_and_cached(monkeypatch):
    monkeypatch.setattr(model_admission, "_OLLAMA_PROBE_CACHE", {})
    monkeypatch.setattr(model_admission, "_ollama_base_url", lambda: "http://127.0.0.1:9")   # discard port: refused
    t0 = time.monotonic()
    assert await model_admission.ollama_reachable() is False
    assert time.monotonic() - t0 < 2
    with patch("httpx.AsyncClient", side_effect=AssertionError("probed again inside the cache window")):
        assert await model_admission.ollama_reachable() is False
