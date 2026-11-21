"""What the Settings page may show about each model provider: is a key on file, and is the provider healthy right now.

Never returns a key, a part of a key, or a provider's own error text (SDK errors quote request ids and credentials).
Health comes from the AHM score and the router's breaker table; both are in-process and say nothing about other tenants
except that a breaker is open somewhere for that provider.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aether_os.core.llm.ahm import default_ahm
from aether_os.core.llm.openrouter_client import base_url as openai_compatible_base_url
from aether_os.core.model_router_providers import _DEAD_PROVIDERS, _is_dead
from aether_os.core.models import OrgApiKey

# id (what the dashboard and /settings/api-keys call it), label, the name the key is stored under, the router/AHM name.
_PROVIDERS = (
    ("anthropic", "Anthropic", "anthropic", "anthropic"),
    ("gemini", "Google Gemini", "google", "gemini"),
    ("openrouter", "OpenRouter / OpenAI-compatible endpoint", "openrouter", "openrouter"),
    ("openai", "OpenAI", "openai", "openai"),
    ("bedrock", "AWS Bedrock", "", "bedrock"),   # IAM credentials of the platform, no key row
)
_ENV_KEYS = {"anthropic": ("ANTHROPIC_API_KEY",), "google": ("GOOGLE_API_KEY",), "openrouter": ("OPENROUTER_API_KEY",),
             "openai": ()}


def endpoint_host(provider: str) -> str:
    """Host of an OpenAI-compatible endpoint (OPENROUTER_BASE_URL), never the full URL: it may carry a path token."""
    if provider != "openrouter":
        return ""
    return urlsplit(openai_compatible_base_url()).hostname or ""


def _breaker_open(name: str) -> bool:
    return any(_is_dead(_DEAD_PROVIDERS, scope, p) for (scope, p) in list(_DEAD_PROVIDERS) if p == name)


def health_of(name: str) -> Dict[str, Any]:
    score = default_ahm.get_health_scores().get(name)
    breaker = _breaker_open(name)
    if breaker:
        state = "down"
    elif score is None:
        state = "unknown"
    elif score < 0.5:
        state = "degraded"
    else:
        state = "healthy"
    return {"state": state, "score": None if score is None else round(score, 2), "breaker_open": breaker}


async def provider_status(session: AsyncSession, org_id: str) -> List[Dict[str, Any]]:
    rows = {r.provider: r.updated_at for r in (await session.execute(
        select(OrgApiKey).where(OrgApiKey.org_id == org_id))).scalars()}
    out = []
    for pid, label, store, router_name in _PROVIDERS:
        out.append({
            "id": pid, "label": label,
            "has_org_key": store in rows,
            "key_updated_at": rows.get(store),
            "platform_key": any(os.environ.get(v) for v in _ENV_KEYS.get(store, ())),
            "endpoint_host": endpoint_host(pid),
            "uses_platform_credentials": pid == "bedrock",
            "health": health_of(router_name),
        })
    return out
