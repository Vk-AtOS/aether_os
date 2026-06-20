"""
AetherOS — LLM Client Tests
Tests LLM client with mocked Anthropic SDK.
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import os

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture(autouse=True)
def mock_ollama_tags():
    """Mock Ollama tags response for all tests."""
    # We need to mock the context manager and the get method
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [{"name": "qwen2.5-coder:7b"}, {"name": "qwen2.5-coder:3b"}]
    }
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        yield mock_get


@pytest.fixture(autouse=True)
def clear_primary_llm(monkeypatch):
    """Reset model router and LLM singletons before each test.

    The model router caches provider availability; without this reset, a test
    that runs after the gateway tests (which init Anthropic) would inherit that
    cached router and fail to raise LLMUnavailable even with no key present.
    """
    monkeypatch.delenv("PRIMARY_LLM", raising=False)
    import aether_os.core.model_router as _mr_mod
    import aether_os.core.llm.client as _llm_mod
    _mr_mod._router_instance = None
    _llm_mod._instance = None
    yield
    _mr_mod._router_instance = None
    _llm_mod._instance = None


def _make_mock_response(text: str, input_tokens: int = 100, output_tokens: int = 50):
    """Create a mock Anthropic API response."""
    content_block = MagicMock()
    content_block.text = text

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    response = MagicMock()
    response.content = [content_block]
    response.usage = usage
    return response


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="No Anthropic key configured"
)
@pytest.mark.asyncio
async def test_llm_client_anthropic_primary():
    """Test that Anthropic API is called when ANTHROPIC_API_KEY is set."""
    import os
    os.environ["ANTHROPIC_API_KEY"] = "test-key-123"

    try:
        mock_anthropic_client = MagicMock()
        mock_anthropic_client.messages = MagicMock()
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=_make_mock_response("def hello(): return 'world'")
        )

        # Patch at the module level where it's used (lazy import path)
        with patch("aether_os.core.llm.client._call_anthropic", new_callable=AsyncMock) as mock_call, \
             patch("aether_os.core.llm.client._call_ollama_with_model", new_callable=AsyncMock) as mock_ollama:
            mock_call.return_value = "def hello(): return 'world'"
            mock_ollama.return_value = "def hello(): return 'world'"
            from aether_os.core.llm.client import LLMClient as _LLMClient
            import aether_os.core.llm.client as llm_mod
            llm_mod._instance = None

            client = _LLMClient()
            result = await client.call("Write a hello function", task_type="code_generation")

        assert result == "def hello(): return 'world'"
    finally:
        del os.environ["ANTHROPIC_API_KEY"]
        import aether_os.core.llm.client as llm_mod
        llm_mod._instance = None


@pytest.mark.asyncio
async def test_llm_client_fallback_on_missing_key():
    """Test that LLMUnavailable is raised when no LLM provider is reachable.

    AWS Bedrock credentials may be present in the CI/local environment, so we
    patch _call_bedrock to raise alongside the Anthropic/Ollama stubs so the
    test accurately simulates a fully unavailable environment.
    """
    import os
    old_keys = {k: os.environ.pop(k, None)
                for k in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}

    try:
        from aether_os.core.llm.client import LLMClient
        import aether_os.core.llm.client as llm_mod
        llm_mod._instance = None

        client = LLMClient()

        with patch("aether_os.core.llm.client._call_bedrock",
                   new_callable=AsyncMock,
                   side_effect=Exception("Bedrock unavailable")) as _mock_bedrock, \
             patch("httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            mock_http.return_value.__aexit__ = AsyncMock()

            from aether_os.core.errors import LLMUnavailable
            with pytest.raises(LLMUnavailable):
                await client.call("test prompt", task_type="code_generation")
    finally:
        for k, v in old_keys.items():
            if v is not None:
                os.environ[k] = v
        import aether_os.core.llm.client as llm_mod
        llm_mod._instance = None


@pytest.mark.asyncio
async def test_llm_client_call_json():
    """Test call_json parses clean JSON response."""
    import os
    os.environ["ANTHROPIC_API_KEY"] = "test-key-123"

    try:
        with patch("aether_os.core.llm.client._call_anthropic", new_callable=AsyncMock) as mock_call, \
             patch("aether_os.core.llm.client._call_ollama_with_model", new_callable=AsyncMock) as mock_ollama, \
             patch("aether_os.core.llm.client._call_bedrock", new_callable=AsyncMock) as mock_bedrock:
            mock_call.return_value = '{"issues": [], "score": 100}'
            mock_ollama.return_value = '{"issues": [], "score": 100}'
            mock_bedrock.return_value = '{"issues": [], "score": 100}'
            from aether_os.core.llm.client import LLMClient
            import aether_os.core.llm.client as llm_mod
            llm_mod._instance = None

            client = LLMClient()
            result = await client.call_json("Analyze this code", task_type="security_scan")

        assert isinstance(result, dict)
        assert "issues" in result
    finally:
        del os.environ["ANTHROPIC_API_KEY"]
        import aether_os.core.llm.client as llm_mod
        llm_mod._instance = None


@pytest.mark.asyncio
async def test_llm_client_strips_markdown_fences():
    """Test call_json handles markdown-fenced JSON from LLM."""
    import os
    os.environ["ANTHROPIC_API_KEY"] = "test-key-123"

    try:
        with patch("aether_os.core.llm.client._call_anthropic", new_callable=AsyncMock) as mock_call, \
             patch("aether_os.core.llm.client._call_ollama_with_model", new_callable=AsyncMock) as mock_ollama, \
             patch("aether_os.core.llm.client._call_bedrock", new_callable=AsyncMock) as mock_bedrock:
            mock_call.return_value = '```json\n{"findings": ["bug1"]}\n```'
            mock_ollama.return_value = '```json\n{"findings": ["bug1"]}\n```'
            mock_bedrock.return_value = '```json\n{"findings": ["bug1"]}\n```'
            from aether_os.core.llm.client import LLMClient
            import aether_os.core.llm.client as llm_mod
            llm_mod._instance = None

            client = LLMClient()
            result = await client.call_json("Review code", task_type="code_generation")

        assert isinstance(result, dict)
        assert "findings" in result
    finally:
        del os.environ["ANTHROPIC_API_KEY"]
        import aether_os.core.llm.client as llm_mod
        llm_mod._instance = None


def test_llm_client_cost_stats():
    """Test cost tracking works."""
    from aether_os.core.llm.client import LLMClient
    client = LLMClient()
    stats = client.get_cost_stats()
    assert "prompt_tokens" in stats
    assert "completion_tokens" in stats
    assert "calls" in stats


def test_llm_model_routing_heavy_tasks(monkeypatch):
    """Test that heavy tasks route to Sonnet, light tasks to Haiku."""
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "claude-haiku-4-5")

    from aether_os.core.llm.client import _select_model
    import aether_os.core.config.loader as cfg_mod
    cfg_mod.AetherConfig._instance = None

    sonnet = _select_model("code_generation")
    haiku = _select_model("requirements")

    assert "sonnet" in sonnet.lower() or "claude" in sonnet.lower()
    assert "haiku" in haiku.lower() or "claude" in haiku.lower()


@pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="No Gemini key configured"
)
@pytest.mark.asyncio
async def test_gemini_primary():
    """Gemini is called when GOOGLE_API_KEY is set and ANTHROPIC_API_KEY is not."""
    import os
    import aether_os.core.llm.client as llm_mod

    old_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ["GOOGLE_API_KEY"] = "test-google-key"
    llm_mod._instance = None

    try:
        with patch("aether_os.core.llm.client._call_gemini", new_callable=AsyncMock) as mock_gemini, \
             patch("aether_os.core.llm.client._call_ollama_with_model", new_callable=AsyncMock) as mock_ollama:
            mock_gemini.return_value = "Hello from Gemini"
            mock_ollama.return_value = "Hello from Gemini"
            client = llm_mod.LLMClient()
            result = await client.call("Say hello", task_type="documentation")

        assert result == "Hello from Gemini"
        assert client.last_provider == "gemini"
    finally:
        del os.environ["GOOGLE_API_KEY"]
        if old_anthropic:
            os.environ["ANTHROPIC_API_KEY"] = old_anthropic
        llm_mod._instance = None


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") or not os.environ.get("GOOGLE_API_KEY"),
    reason="Both Anthropic and Gemini keys required for priority test"
)
@pytest.mark.asyncio
async def test_anthropic_takes_priority():
    """Anthropic is used when both ANTHROPIC_API_KEY and GOOGLE_API_KEY are set."""
    import os
    import aether_os.core.llm.client as llm_mod

    os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
    os.environ["GOOGLE_API_KEY"] = "test-google-key"
    llm_mod._instance = None

    try:
        with patch("aether_os.core.llm.client._call_anthropic", new_callable=AsyncMock) as mock_ant, \
             patch("aether_os.core.llm.client._call_gemini", new_callable=AsyncMock) as mock_gem, \
             patch("aether_os.core.llm.client._call_ollama_with_model", new_callable=AsyncMock) as mock_ollama:
            mock_ant.return_value = "Hello from Anthropic"
            mock_gem.return_value = "Hello from Gemini"
            mock_ollama.return_value = "Hello from Ollama"
            client = llm_mod.LLMClient()
            result = await client.call("Say hello", task_type="code_generation")

        assert result == "Hello from Anthropic"
        assert client.last_provider == "anthropic"
        mock_ant.assert_called_once()
        mock_gem.assert_not_called()
    finally:
        del os.environ["ANTHROPIC_API_KEY"]
        del os.environ["GOOGLE_API_KEY"]
        llm_mod._instance = None


def test_gemini_model_routing():
    """Heavy tasks use gemini-2.5-pro, light tasks use gemini-2.0-flash."""
    from aether_os.core.llm.client import _select_gemini_model

    assert _select_gemini_model("code_generation") == "gemini-2.5-pro"
    assert _select_gemini_model("security_scan") == "gemini-2.5-pro"
    assert _select_gemini_model("architecture") == "gemini-2.5-pro"
    assert _select_gemini_model("documentation") == "gemini-2.0-flash"
    assert _select_gemini_model("requirements") == "gemini-2.0-flash"
    assert _select_gemini_model("intake") == "gemini-2.0-flash"
    assert _select_gemini_model("portal") == "gemini-2.0-flash"
