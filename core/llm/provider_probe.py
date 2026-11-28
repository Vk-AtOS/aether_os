"""Is a chain entry reachable, not just configured? (KAN-260)

`_is_provider_configured` treats Ollama as always available, so a chain ended in `ollama/qwen2.5-coder:3b` on a server
with no Ollama and every exhausted chain reported "All connection attempts failed" for a provider nobody runs. The
router now asks here before it tries an Ollama entry: the answer comes from one GET of /api/tags (is the server up and
is THIS model pulled), cached so a chain walk does not pay for it twice.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# base_url -> (monotonic expiry, installed model names or None when unreachable, reason)
_CACHE: Dict[str, Tuple[float, Optional[frozenset], str]] = {}


def _base_url() -> str:
    from aether_os.core.config.loader import get_config
    return str(get_config().get("llm.ollama_base_url", "http://localhost:11434")).rstrip("/")


async def _installed_models(base: str) -> Tuple[Optional[frozenset], str]:
    cached = _CACHE.get(base)
    if cached and cached[0] > time.monotonic():
        return cached[1], cached[2]
    timeout = float(os.environ.get("OLLAMA_PROBE_TIMEOUT_S", "0.5"))
    names: Optional[frozenset] = None
    reason = ""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base}/api/tags")
        if resp.status_code == 200:
            names = frozenset(m.get("name", "") for m in resp.json().get("models", []))
        else:
            reason = f"{base}/api/tags answered HTTP {resp.status_code}"
    except Exception as e:
        reason = f"Ollama at {base} is not reachable ({type(e).__name__}: {e or 'no route'})"
        logger.info("Provider probe: %s", reason)
    ttl = float(os.environ.get("OLLAMA_PROBE_CACHE_S", "30" if names is not None else "15"))
    _CACHE[base] = (time.monotonic() + ttl, names, reason)
    return names, reason


async def ollama_model_unavailable(model: str) -> str:
    """"" when Ollama is up and has `model`; otherwise the reason it cannot serve it."""
    base = _base_url()
    names, reason = await _installed_models(base)
    if names is None:
        return reason
    if model not in names and f"{model}:latest" not in names:
        return f"Ollama at {base} is up but model {model!r} is not pulled (has: {', '.join(sorted(names)) or 'none'})"
    return ""
