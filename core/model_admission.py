"""
AetherOS — Model provider admission check (KAN-207)
=====================================================
Is any provider in the model chain usable right now? Asked by POST /factory/start
before a run is admitted: with no usable provider a run would be created, start,
and fail at its first model call.

"Usable" mirrors the router's own skip rules (core/model_router.py), in chain order:
  - the provider has a key (the org's own or the platform's) or is otherwise
    configured (_is_provider_configured), and
  - its circuit breaker (provider or provider/model, in the caller's scope) is not open, and
  - for Ollama only: it answers a short HTTP probe. _is_provider_configured treats
    Ollama as always available, but deployments without it (the AWS testbed) would
    then admit every run. The probe result is cached so starts do not pay for it.

No paid provider is ever called here: configuration and breaker state are local
(org keys come from the api_key_store cache/DB), and Ollama is only probed when no
provider earlier in the chain is usable.
"""
from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import httpx

from aether_os.core.config.loader import get_config
from aether_os.core.model_router import _breaker_scope, _provider_key
from aether_os.core.model_router_providers import (
    _DEAD_MODELS,
    _DEAD_PROVIDERS,
    _apply_org_chain_overrides,
    _is_provider_configured,
    _is_provider_dead,
    get_fallback_chain,
)

logger = logging.getLogger(__name__)

# base_url -> (monotonic expiry, reachable)
_OLLAMA_PROBE_CACHE: Dict[str, Tuple[float, bool]] = {}


@dataclass
class ModelAdmission:
    usable: bool
    provider: str = ""          # first usable provider, when usable
    retry_after_s: int = 0      # when not usable: how long until it may be
    reason: str = ""            # when not usable: what is missing, for the 503 message


def _ollama_base_url() -> str:
    # Same setting the Ollama client uses (core/llm/providers.py _call_ollama_with_model).
    return str(get_config().get("llm.ollama_base_url", "http://localhost:11434")).rstrip("/")


async def ollama_reachable() -> bool:
    """True when Ollama answers /api/tags within OLLAMA_PROBE_TIMEOUT_S; cached per base URL."""
    base = _ollama_base_url()
    now = time.monotonic()
    cached = _OLLAMA_PROBE_CACHE.get(base)
    if cached and cached[0] > now:
        return cached[1]
    timeout = float(os.environ.get("OLLAMA_PROBE_TIMEOUT_S", "0.5"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            ok = (await client.get(f"{base}/api/tags")).status_code == 200
    except Exception as e:
        logger.info("Model admission: Ollama at %s not reachable: %s", base, e)
        ok = False
    ttl = float(os.environ.get("OLLAMA_PROBE_CACHE_S", "30" if ok else "15"))
    _OLLAMA_PROBE_CACHE[base] = (time.monotonic() + ttl, ok)
    return ok


def _breaker_remaining_s(provider: str, model: str, scope: str) -> float:
    """Seconds until every open breaker covering provider/model has expired."""
    now = time.monotonic()
    expiries = (_DEAD_PROVIDERS.get((scope, provider)), _DEAD_MODELS.get((scope, f"{provider}/{model}")))
    return max([e - now for e in expiries if e is not None] or [0.0])


async def check_model_admission(org_id: Optional[str]) -> ModelAdmission:
    """Return whether a new run for org_id has at least one usable model provider."""
    chain = get_fallback_chain()
    if org_id:
        chain = await _apply_org_chain_overrides(chain, org_id)

    breaker_waits = []
    for spec in chain:
        api_key = await _provider_key(spec.provider, org_id)
        if not api_key and not _is_provider_configured(spec):
            continue
        scope = await _breaker_scope(spec.provider, org_id, api_key)
        if _is_provider_dead(spec.provider, spec.model, scope):
            breaker_waits.append(_breaker_remaining_s(spec.provider, spec.model, scope))
            continue
        if spec.provider == "ollama" and not await ollama_reachable():
            continue
        return ModelAdmission(usable=True, provider=spec.provider)

    default_wait = int(os.environ.get("MODEL_UNAVAILABLE_RETRY_AFTER_S", "60"))
    if breaker_waits:
        # A breaker closes on its own: tell the client when the first one does.
        return ModelAdmission(usable=False, retry_after_s=max(1, math.ceil(min(breaker_waits))),
                              reason="every configured provider's circuit breaker is open")
    return ModelAdmission(usable=False, retry_after_s=default_wait,
                          reason="no provider is configured and Ollama is not reachable")
