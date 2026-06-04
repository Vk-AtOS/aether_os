"""
AetherOS — ModelRouter + LangSmith tracer tests.

All tests are self-contained and work offline (no real LLM calls, no network).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_router_state():
    """Reset ModelRouter singleton and module stats between tests."""
    import aether_os.core.model_router as _mod
    _mod._router_instance = None
    _mod._active_model = None
    _mod._fallback_count_today = 0
    _mod._fallback_date = ""
    _mod._DEAD_PROVIDERS.clear()
    yield
    _mod._router_instance = None
    _mod._active_model = None
    _mod._fallback_count_today = 0
    _mod._fallback_date = ""
    _mod._DEAD_PROVIDERS.clear()


@pytest.fixture(autouse=True)
def strip_api_keys(monkeypatch):
    """Remove cloud API keys so only Ollama is active by default."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("BEDROCK_ENABLED", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("PRIMARY_LLM", "anthropic")


# ── FALLBACK_CHAIN structure ──────────────────────────────────────────────────

@pytest.fixture
def clean_env_chain(monkeypatch):
    """Ensure a consistent environment for chain structure tests."""
    monkeypatch.setenv("PRIMARY_LLM", "anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5-coder:3b")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "120")
    monkeypatch.delenv("BEDROCK_ENABLED", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSy-test-key-abc-1234567890")
    # Fix OPENROUTER_FALLBACK_MODELS to exactly 4 to get deterministic chain length
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODELS", "model-a,model-b,model-c,model-d")
    # Force re-call of get_fallback_chain
    from aether_os.core.model_router import get_fallback_chain
    return get_fallback_chain()


def test_fallback_chain_has_expected_length(clean_env_chain):
    # Chain has: anthropic (1) + gemini (1) + openrouter (4 defaults) + ollama (1) = 7
    assert len(clean_env_chain) == 7


def test_fallback_chain_order(clean_env_chain):
    """Chain must be: anthropic → gemini → 4x openrouter → ollama."""
    providers = [s.provider for s in clean_env_chain]
    assert providers[0] == "anthropic"
    assert providers[1] == "gemini"
    assert providers[2:6] == ["openrouter"] * 4
    assert providers[6] == "ollama"


def test_model_identifiers(clean_env_chain):
    specs = {s.provider: s for s in clean_env_chain}
    assert specs["anthropic"].model == "claude-sonnet-4-6"
    assert specs["gemini"].model == "gemini-2.5-flash"
    assert specs["ollama"].model == "qwen2.5-coder:3b"


def test_retry_counts(clean_env_chain):
    for spec in clean_env_chain:
        if spec.provider == "ollama":
            assert spec.retry_count == 1
        else:
            assert spec.retry_count == 2


# ── Error classification ──────────────────────────────────────────────────────

def test_classify_rate_limit_as_retry():
    from aether_os.core.model_router import _classify_error
    assert _classify_error(Exception("rate limit exceeded")) == "retry"


def test_classify_429_as_retry():
    from aether_os.core.model_router import _classify_error
    assert _classify_error(Exception("HTTP 429 Too Many Requests")) == "retry"


def test_classify_overloaded_as_retry():
    from aether_os.core.model_router import _classify_error
    assert _classify_error(Exception("model overloaded, try again")) == "retry"


def test_classify_bad_api_key_as_fallback():
    from aether_os.core.model_router import _classify_error
    assert _classify_error(Exception("invalid_api_key")) == "fallback"


def test_classify_import_error_as_fallback():
    from aether_os.core.model_router import _classify_error
    assert _classify_error(ImportError("SDK not installed")) == "fallback"


def test_classify_runtime_error_as_fallback():
    from aether_os.core.model_router import _classify_error
    assert _classify_error(RuntimeError("connection refused")) == "fallback"


def test_classify_timeout_as_fallback():
    import asyncio
    from aether_os.core.model_router import _classify_error
    assert _classify_error(asyncio.TimeoutError()) == "fallback"


# ── Provider configuration detection ─────────────────────────────────────────

def test_anthropic_not_configured_without_key():
    from aether_os.core.model_router import _is_provider_configured, ModelSpec
    spec = ModelSpec("anthropic", "claude-sonnet-4-6", 30, 2)
    assert _is_provider_configured(spec) is False


def test_anthropic_configured_with_key(monkeypatch):
    from aether_os.core.model_router import _is_provider_configured, ModelSpec
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    spec = ModelSpec("anthropic", "claude-sonnet-4-6", 30, 2)
    assert _is_provider_configured(spec) is True


def test_gemini_not_configured_with_placeholder(monkeypatch):
    from aether_os.core.model_router import _is_provider_configured, ModelSpec
    monkeypatch.setenv("GOOGLE_API_KEY", "REPLACE_WITH_YOUR_GEMINI_KEY")
    spec = ModelSpec("gemini", "gemini-2.5-flash", 45, 2)
    assert _is_provider_configured(spec) is False


def test_gemini_configured_with_real_key(monkeypatch):
    from aether_os.core.model_router import _is_provider_configured, ModelSpec
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSy-real-key-here")
    spec = ModelSpec("gemini", "gemini-2.5-flash", 45, 2)
    assert _is_provider_configured(spec) is True


def test_ollama_always_configured():
    from aether_os.core.model_router import _is_provider_configured, FALLBACK_CHAIN, ModelSpec
    # Find ollama spec by provider name (index changes when PRIMARY_LLM is set)
    ollama_spec = next(s for s in FALLBACK_CHAIN if s.provider == "ollama")
    assert _is_provider_configured(ollama_spec) is True


# ── Router.call() — success paths ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_router_uses_anthropic_when_key_present(monkeypatch):
    """Router calls Anthropic when key is set; sets last_provider = 'anthropic'."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with patch("aether_os.core.llm.client._call_anthropic", new_callable=AsyncMock) as mock_ant:
        mock_ant.return_value = "hello from anthropic"
        from aether_os.core.model_router import ModelRouter
        router = ModelRouter()
        result, provider = await router.call("say hi", task_type="code_generation")
        assert result == "hello from anthropic"
        assert provider == "anthropic"
        assert router.last_provider == "anthropic"
        mock_ant.assert_called_once()


@pytest.mark.asyncio
async def test_router_falls_back_to_ollama_without_cloud_keys():
    """Without cloud keys, Ollama is used."""
    with patch("aether_os.core.llm.client._call_ollama_with_model", new_callable=AsyncMock) as mock_ol:
        mock_ol.return_value = "hello from ollama"
        from aether_os.core.model_router import ModelRouter
        router = ModelRouter()
        result, provider = await router.call("say hi")
        assert result == "hello from ollama"
        assert provider == "ollama"


@pytest.mark.asyncio
async def test_router_skips_anthropic_falls_back_to_gemini(monkeypatch):
    """When Anthropic fails with a hard error, router tries Gemini next."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-bad")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSy-good")
    with patch("aether_os.core.llm.client._call_anthropic",
               new_callable=AsyncMock,
               side_effect=RuntimeError("invalid_api_key")) as mock_ant, \
         patch("aether_os.core.llm.client._call_gemini",
               new_callable=AsyncMock) as mock_gem:
        mock_gem.return_value = "hello from gemini"
        from aether_os.core.model_router import ModelRouter, _fallback_count_today
        router = ModelRouter()
        result, provider = await router.call("say hi")
        assert result == "hello from gemini"
        assert provider == "gemini"
        mock_ant.assert_called_once()
        mock_gem.assert_called_once()


@pytest.mark.asyncio
async def test_fallback_count_increments_on_chain_advance(monkeypatch):
    """fallback_count_today increases each time we move to the next tier."""
    import aether_os.core.model_router as _mod
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-bad")
    with patch("aether_os.core.llm.client._call_anthropic",
               new_callable=AsyncMock,
               side_effect=RuntimeError("invalid_api_key")), \
         patch("aether_os.core.llm.client._call_ollama_with_model",
               new_callable=AsyncMock,
               return_value="hello from ollama — this is a complete response"):
        from aether_os.core.model_router import ModelRouter
        router = ModelRouter()
        await router.call("hi")
        assert _mod._fallback_count_today >= 1


# ── Router.call() — failure path ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_router_raises_llm_unavailable_when_all_fail():
    """LLMUnavailable raised when every model in the chain fails."""
    with patch("aether_os.core.llm.client._call_ollama_with_model",
               new_callable=AsyncMock,
               side_effect=RuntimeError("Ollama not running")):
        from aether_os.core.errors import LLMUnavailable
        from aether_os.core.model_router import ModelRouter
        router = ModelRouter()
        with pytest.raises(LLMUnavailable):
            await router.call("hi")


# ── get_status() ─────────────────────────────────────────────────────────────

def test_get_status_structure():
    from aether_os.core.model_router import ModelRouter
    status = ModelRouter().get_status()
    assert "active_model" in status
    assert "fallback_count_today" in status
    assert "model_availability" in status
    avail = status["model_availability"]
    assert "anthropic" in avail
    assert "ollama" in avail


def test_get_router_returns_singleton():
    from aether_os.core.model_router import get_router
    r1 = get_router()
    r2 = get_router()
    assert r1 is r2


# ── LangSmith tracer — graceful degradation ───────────────────────────────────

def test_langsmith_disabled_without_key(monkeypatch):
    """is_connected() returns False when no LANGSMITH_API_KEY is set."""
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    import aether_os.core.telemetry.langsmith_tracer as _ls
    _ls._connected = False
    _ls._ls_client = None
    result = _ls.init_langsmith()
    assert result is False
    assert _ls.is_connected() is False


def test_langsmith_get_status_structure(monkeypatch):
    """get_status() always returns the expected keys."""
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    import aether_os.core.telemetry.langsmith_tracer as _ls
    _ls._connected = False
    status = _ls.get_status()
    assert "langsmith" in status
    assert "last_trace_id" in status
    assert "traces_today" in status
    assert status["langsmith"] == "disabled"


@pytest.mark.asyncio
async def test_trace_call_is_noop_when_disabled():
    """trace_call() yields None and never raises when LangSmith is disabled."""
    import aether_os.core.telemetry.langsmith_tracer as _ls
    _ls._connected = False
    _ls._ls_client = None
    async with _ls.trace_call("test_run", inputs={"x": 1}) as trace_id:
        assert trace_id is None   # no-op


@pytest.mark.asyncio
async def test_trace_call_propagates_exceptions():
    """Exceptions inside trace_call() are never suppressed."""
    import aether_os.core.telemetry.langsmith_tracer as _ls
    _ls._connected = False
    with pytest.raises(ValueError, match="deliberate"):
        async with _ls.trace_call("test_run"):
            raise ValueError("deliberate")
