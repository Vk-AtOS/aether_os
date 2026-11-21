"""An organisation without its own LLM settings is shown what the platform really runs on (PRIMARY_LLM), not a fixed
"anthropic / no key" (production on 22 Nov 2026 showed MODEL NOT READY while every call worked through openrouter)."""
import asyncio

from aether_os.gateway.routers import settings_advanced_router as r


def _cfg(monkeypatch, env):
    for k in ("PRIMARY_LLM", "OPENROUTER_API_KEY", "OPENROUTER_HEAVY_MODEL", "OPENROUTER_LIGHT_MODEL", "ANTHROPIC_API_KEY",
              "BEDROCK_ENABLED", "AWS_BEARER_TOKEN_BEDROCK", "AWS_ACCESS_KEY_ID"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    async def no_org_key(provider, org_id):
        return None
    monkeypatch.setattr(r, "get_api_key", no_org_key)
    return asyncio.run(r._platform_default_config("org-x"))


def test_openrouter_platform_is_reported_with_its_key_and_models(monkeypatch):
    cfg = _cfg(monkeypatch, {"PRIMARY_LLM": "openrouter", "OPENROUTER_API_KEY": "k",
                             "OPENROUTER_HEAVY_MODEL": "nvidia/heavy", "OPENROUTER_LIGHT_MODEL": "nvidia/light"})
    assert cfg["primary_llm"] == "openrouter" and cfg["primary_key_configured"] is True
    assert cfg["openrouter_heavy_model"] == "nvidia/heavy" and cfg["openrouter_light_model"] == "nvidia/light"


def test_default_is_still_anthropic_when_the_platform_names_none(monkeypatch):
    cfg = _cfg(monkeypatch, {})
    assert cfg["primary_llm"] == "anthropic" and cfg["primary_key_configured"] is False


def test_missing_platform_key_is_reported_as_not_configured(monkeypatch):
    cfg = _cfg(monkeypatch, {"PRIMARY_LLM": "openrouter"})
    assert cfg["primary_llm"] == "openrouter" and cfg["primary_key_configured"] is False
