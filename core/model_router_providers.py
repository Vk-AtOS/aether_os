"""
AetherOS — Model Router Provider Helpers
==========================================
Provider chain configuration, error classification, circuit breaker, and
org-specific overrides extracted from model_router.py to keep it under 600 lines.

Exported:
    ModelSpec               — dataclass describing a single model+provider
    get_fallback_chain()    — build fallback chain from environment
    _is_provider_configured() — check if a provider has credentials
    _classify_error()       — retry vs fallback decision
    _mark_provider_dead()   — open circuit breaker for a provider/model, per scope
    _is_provider_dead()     — is the breaker open for this provider/model in a scope
    _apply_org_chain_overrides() — filter chain per org DB settings
    _DEAD_PROVIDERS         — breaker table {(scope, provider): expiry}
    _DEAD_MODELS            — breaker table {(scope, provider/model): expiry}
    _RETRY_PATTERNS         — transient error substrings
    _FALLBACK_PATTERNS      — hard failure substrings
    FALLBACK_CHAIN          — legacy alias (do not use; call get_fallback_chain())
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)


# ── Model specification ───────────────────────────────────────────────────────

@dataclass
class ModelSpec:
    provider: str           # "anthropic" | "gemini" | "ollama"
    model: str              # exact model identifier
    timeout_seconds: int    # asyncio.wait_for timeout
    retry_count: int        # attempts before moving to next model


_DEFAULT_FALLBACK_MODELS = (
    "meta-llama/llama-3.3-70b-instruct:free,"
    "nousresearch/hermes-3-llama-3.1-405b:free,"
    "meta-llama/llama-3.2-3b-instruct:free,"
    "mistralai/mistral-7b-instruct:free,"
    "google/gemma-3-27b-it:free"
)


def _is_provider_configured(spec: ModelSpec) -> bool:
    """Return True if the provider has usable credentials / can be reached."""
    if spec.provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if spec.provider == "gemini":
        key = os.environ.get("GOOGLE_API_KEY", "").strip()
        # Platform key only. An org's own key is resolved per call by the router
        # (_provider_key); another org having one cached says nothing about this caller.
        return bool(key) and len(key) > 10 and not key.startswith("REPLACE")
    if spec.provider == "openrouter":
        return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    if spec.provider == "bedrock":
        # Respect explicit opt-out via BEDROCK_ENABLED=false
        if os.environ.get("BEDROCK_ENABLED", "").lower() == "false":
            return False
        # Auto-enable when explicit credentials are provided (most common setup)
        if os.environ.get("AWS_ACCESS_KEY_ID", "").strip():
            return True
        # Also enable if explicitly opted-in (for IAM role / EC2 instance profile auth)
        return os.environ.get("BEDROCK_ENABLED", "false").lower() == "true"
    # Ollama: always attempt — will fail at call time if not running
    return True


def get_fallback_chain() -> List[ModelSpec]:
    """Build fallback chain from environment.

    Design rules (post-2026-06 audit):
      - **single retry** per provider — the previous 2-retry-per-tier policy
        could blow a phase past 10 min when free-tier OpenRouter rotated 429s.
      - **fast 60s timeout** per cloud provider — anything slower is not
        acceptable in a 180s phase budget with one call per phase.
      - **Bedrock heavy + fallback + Ollama** is the production default. The
        Anthropic / OpenRouter / Gemini tiers are only added if their key is
        configured.

    OFFLINE_MODE=true restricts the chain to Ollama only (air-gapped deploys).
    """
    # ── Air-gapped / offline mode ─────────────────────────────────────────────
    if os.environ.get("OFFLINE_MODE", "").lower() == "true":
        ollama_model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        ollama_timeout = int(os.environ.get("OLLAMA_TIMEOUT", "300"))
        logger.info(
            "OFFLINE_MODE=true — restricting LLM chain to Ollama only (model=%s)",
            ollama_model,
        )
        return [ModelSpec("ollama", ollama_model, ollama_timeout, 1)]

    primary = os.environ.get("PRIMARY_LLM", "bedrock").lower()
    anthropic_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    ollama_model = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:3b")
    ollama_timeout = int(os.environ.get("OLLAMA_TIMEOUT", "120"))

    # OpenRouter chain (only if explicitly configured — empty by default now)
    fallback_env = os.environ.get("OPENROUTER_FALLBACK_MODELS", "").strip()
    openrouter_models: List[str] = []
    if fallback_env:
        openrouter_models = [m.strip() for m in fallback_env.split(",") if m.strip()]
    elif os.environ.get("OPENROUTER_HEAVY_MODEL", "").strip():
        heavy = os.environ.get("OPENROUTER_HEAVY_MODEL", "").strip()
        defaults = [m.strip() for m in _DEFAULT_FALLBACK_MODELS.split(",")]
        openrouter_models = list(dict.fromkeys([heavy] + defaults))

    bedrock_heavy = os.environ.get("BEDROCK_MODEL_HEAVY", "us.amazon.nova-pro-v1:0")
    bedrock_fallback_model = os.environ.get(
        "BEDROCK_MODEL_FALLBACK", "us.meta.llama3-3-70b-instruct-v1:0"
    )
    bedrock_timeout = int(os.environ.get("BEDROCK_TIMEOUT", "60"))

    non_openrouter = {
        "anthropic": ModelSpec("anthropic", anthropic_model, 60, 1),
        "bedrock":   ModelSpec("bedrock",   bedrock_heavy,   bedrock_timeout, 1),
        "bedrock_fb": ModelSpec("bedrock",  bedrock_fallback_model, bedrock_timeout, 1),
        "gemini":    ModelSpec("gemini",    "gemini-2.5-flash", 45, 1),
        "ollama":    ModelSpec("ollama",    ollama_model, ollama_timeout, 1),
    }

    chain: List[ModelSpec] = []

    if primary in non_openrouter:
        chain.append(non_openrouter[primary])

    if primary == "openrouter":
        for m in openrouter_models:
            chain.append(ModelSpec("openrouter", m, 60, 1))
        for p in ("bedrock", "anthropic", "gemini", "ollama"):
            if p != primary and _is_provider_configured(non_openrouter[p]):
                chain.append(non_openrouter[p])
    else:
        # Bedrock fallback model (e.g. Llama 3.3 70B) before any 3rd-party tier
        if primary == "bedrock" and bedrock_fallback_model != bedrock_heavy:
            chain.append(non_openrouter["bedrock_fb"])
        for p in ("anthropic", "gemini"):
            if p != primary and _is_provider_configured(non_openrouter[p]):
                chain.append(non_openrouter[p])
        for m in openrouter_models:
            chain.append(ModelSpec("openrouter", m, 60, 1))
        if primary != "ollama":
            chain.append(non_openrouter["ollama"])

    return chain


FALLBACK_CHAIN = get_fallback_chain()  # legacy alias — do not use; call get_fallback_chain() directly

# Error-message substrings → retry (transient, worth retrying same model)
_RETRY_PATTERNS = ("rate limit", "429", "overloaded", "server error", "503", "502")
# Error-message substrings → fallback (hard failure, skip to next model)
_FALLBACK_PATTERNS = (
    "api key", "authentication", "invalid_api_key", "unauthorized",
    "not installed", "model not found", "no such model",
    # Bedrock-specific hard failures
    "accessdeniedexception", "invalid_payment_instrument", "invalidpaymentinstrument",
    "not authorized", "validationexception", "resourcenotfoundexception",
    "end of its life", "no longer supported",
)


def _classify_error(exc: Exception) -> str:
    """Return "retry" for transient errors, "fallback" for hard failures."""
    msg = str(exc).lower()
    if any(p in msg for p in _RETRY_PATTERNS):
        return "retry"
    if any(p in msg for p in _FALLBACK_PATTERNS):
        return "fallback"
    # ImportError / RuntimeError("not installed") are always hard failures
    if isinstance(exc, (ImportError, RuntimeError)):
        return "fallback"
    # asyncio.TimeoutError → fallback (the model was too slow; try the next tier)
    if isinstance(exc, asyncio.TimeoutError):
        return "fallback"
    # Default: fallback on unknown errors to preserve pipeline progress
    return "fallback"


# Circuit breaker for permanent hard failures (bad key, no payment).
# Keyed by (scope, name) -> monotonic expiry. `scope` is the org id when the call
# used that org's own key, and PLATFORM_SCOPE when it used the platform key (or a
# keyless provider): one org's bad key must not disable the provider for the rest.
# Entries expire so a provider recovers once the key or account is fixed.
PLATFORM_SCOPE = ""
_DEAD_PROVIDERS: dict[tuple[str, str], float] = {}
_DEAD_MODELS: dict[tuple[str, str], float] = {}


def _dead_ttl() -> float:
    return float(os.environ.get("ROUTER_DEAD_PROVIDER_TTL_SECONDS", "600"))


def _is_dead(table: dict, scope: str, name: str) -> bool:
    expiry = table.get((scope, name))
    if expiry is None:
        return False
    if expiry <= time.monotonic():
        del table[(scope, name)]  # expired: let the next call try again
        return False
    return True


def _is_provider_dead(provider: str, model: str = "", scope: str = PLATFORM_SCOPE) -> bool:
    """True while the breaker is open for this provider (or provider/model) in `scope`."""
    return _is_dead(_DEAD_PROVIDERS, scope, provider) or (
        bool(model) and _is_dead(_DEAD_MODELS, scope, f"{provider}/{model}"))


_PERMANENT_FAILURE_PATTERNS = (
    "invalid_payment_instrument", "invalidpaymentinstrument",
    "invalid_api_key", "invalid api key",
    "is not available for this account",
    "resourcenotfoundexception",
)
# Patterns that mean THIS MODEL is broken, but the provider as a whole may still
# work for other models (e.g. account has Nova but not Claude on Bedrock).
_MODEL_SPECIFIC_FAILURE_PATTERNS = (
    "is not available for this account",
    "invalid_payment_instrument", "invalidpaymentinstrument",
    "resourcenotfoundexception",
    "marketplace",
)


def _mark_provider_dead(provider: str, exc: Exception, model: str = "",
                        scope: str = PLATFORM_SCOPE) -> None:
    """Open the circuit breaker, within `scope`, for a single model or a whole provider.

    Mark only the MODEL dead when the failure is account-specific (Bedrock
    Marketplace subscription missing, invalid payment for one model family) —
    other models on the same provider may still work.

    Mark the PROVIDER dead only for credential-level failures (invalid key).
    """
    msg = str(exc).lower()
    where = f"org {scope[:8]}" if scope else "the platform key"
    if model and any(p in msg for p in _MODEL_SPECIFIC_FAILURE_PATTERNS):
        key = f"{provider}/{model}"
        if not _is_dead(_DEAD_MODELS, scope, key):
            logger.warning(
                "Router: circuit-breaker OPEN for model %s (%s) — account-specific failure, "
                "skipping for %.0fs", key, where, _dead_ttl())
        _DEAD_MODELS[(scope, key)] = time.monotonic() + _dead_ttl()
        return
    if "invalid_api_key" in msg or "invalid api key" in msg:
        if not _is_dead(_DEAD_PROVIDERS, scope, provider):
            logger.warning(
                "Router: circuit-breaker OPEN for %s (%s) — bad credentials, "
                "skipping for %.0fs", provider, where, _dead_ttl())
        _DEAD_PROVIDERS[(scope, provider)] = time.monotonic() + _dead_ttl()


async def _apply_org_chain_overrides(
    chain: List[ModelSpec], org_id: str
) -> List[ModelSpec]:
    """Filter/extend chain based on org's DB settings (bedrock_enabled, stored API keys)."""
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import LlmConfig
        from aether_os.core.api_key_store import get_api_key
        from sqlalchemy import select

        async with get_session_factory()() as session:
            cfg = (await session.execute(
                select(LlmConfig).where(LlmConfig.org_id == org_id)
            )).scalar_one_or_none()

        filtered: List[ModelSpec] = []
        has_gemini = False
        has_openrouter = False
        bedrock_primary_updated = False

        for spec in chain:
            # Remove bedrock if DB says it's disabled for this org
            if spec.provider == "bedrock" and cfg is not None and not cfg.bedrock_enabled:
                logger.debug("Router: org %s has bedrock_enabled=False — removing from chain", org_id[:8])
                continue
            # Override first bedrock spec's model with DB-configured heavy model
            if (spec.provider == "bedrock" and not bedrock_primary_updated
                    and cfg is not None and cfg.bedrock_model_heavy):
                spec = ModelSpec(spec.provider, cfg.bedrock_model_heavy, spec.timeout_seconds, spec.retry_count)
                bedrock_primary_updated = True
                logger.debug("Router: org %s bedrock model overridden to %s", org_id[:8], cfg.bedrock_model_heavy)
            if spec.provider == "gemini":
                has_gemini = True
            if spec.provider == "openrouter":
                has_openrouter = True
            filtered.append(spec)

        # Add gemini from DB key if not already in chain and env var is absent
        if not has_gemini and not os.environ.get("GOOGLE_API_KEY", "").strip():
            gemini_key = await get_api_key("google", org_id)
            if gemini_key:
                insert_at = next(
                    (i for i, s in enumerate(filtered) if s.provider == "openrouter"),
                    len(filtered),
                )
                filtered.insert(insert_at, ModelSpec("gemini", "gemini-2.5-flash", 45, 2))
                logger.info("Router: injected gemini into chain from org DB key (org=%s)", org_id[:8])

        # Add openrouter from DB key if not already in chain and env var is absent
        if not has_openrouter and not os.environ.get("OPENROUTER_API_KEY", "").strip():
            or_key = await get_api_key("openrouter", org_id)
            if or_key:
                heavy = os.environ.get("OPENROUTER_HEAVY_MODEL", "minimax/minimax-m2.5:free")
                filtered.append(ModelSpec("openrouter", heavy, 60, 2))
                logger.info("Router: injected openrouter into chain from org DB key (org=%s)", org_id[:8])

        return filtered if filtered else chain  # never return empty
    except Exception as exc:
        logger.debug("_apply_org_chain_overrides failed (using raw chain): %s", exc)
        return chain
