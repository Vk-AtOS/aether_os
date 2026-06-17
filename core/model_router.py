"""
AetherOS — Multi-Model Router

Fallback chain (in priority order):
  1. Anthropic  claude-sonnet-4-6   — 30 s timeout, 2 retries
  2. Gemini     gemini-2.5-flash    — 45 s timeout, 2 retries
  3. Ollama     qwen2.5-coder:3b    — 90 s timeout, 2 retries

Each provider is skipped if its credentials are absent.
Retry vs fallback decision is based on error-message classification:
  retry    — transient (rate limit, 429, server overload)
  fallback — hard failure (bad key, SDK missing, model not found)

Which model served each request is logged at INFO level and visible
in LangSmith traces (phase_name + run_id).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Strong references prevent GC from silently killing background tasks
_background_tasks: set = set()

# ── Module-level stats (reset on process restart) ─────────────────────────────
_active_model: Optional[str] = None        # e.g. "anthropic/claude-sonnet-4-6"
_fallback_count_today: int = 0
_fallback_date: str = ""


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
        if bool(key) and len(key) > 10 and not key.startswith("REPLACE"):
            return True
        # Also check if any org key is cached (populated by init_org_llm_context)
        try:
            from aether_os.core.api_key_store import _cache as _KEY_CACHE
            return any(k[1] == "google" for k in _KEY_CACHE)
        except Exception as exc:
            logger.debug("Google org key cache check failed: %s", exc)
            return False
    if spec.provider == "openrouter":
        if bool(os.environ.get("OPENROUTER_API_KEY", "").strip()):
            return True
        try:
            from aether_os.core.api_key_store import _cache as _KEY_CACHE
            return any(k[1] == "openrouter" for k in _KEY_CACHE)
        except Exception as exc:
            logger.debug("OpenRouter org key cache check failed: %s", exc)
            return False
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


# Process-level circuit breaker — providers that have hit a permanent hard failure
# (e.g. INVALID_PAYMENT_INSTRUMENT, bad key) are added here and skipped for the
# remainder of the process lifetime, saving 1-2s per call on every subsequent request.
# We also track DEAD MODELS so a single broken Bedrock model ID (e.g. an
# Anthropic-on-Bedrock model the account isn't subscribed to) doesn't take down
# every Bedrock call — only that specific model.
_DEAD_PROVIDERS: set[str] = set()
_DEAD_MODELS: set[str] = set()
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


def _mark_provider_dead(provider: str, exc: Exception, model: str = "") -> None:
    """Open the circuit breaker for either a single model or a whole provider.

    Mark only the MODEL dead when the failure is account-specific (Bedrock
    Marketplace subscription missing, invalid payment for one model family) —
    other models on the same provider may still work.

    Mark the PROVIDER dead only for credential-level failures (invalid key).
    """
    msg = str(exc).lower()
    if model and any(p in msg for p in _MODEL_SPECIFIC_FAILURE_PATTERNS):
        key = f"{provider}/{model}"
        if key not in _DEAD_MODELS:
            _DEAD_MODELS.add(key)
            logger.warning("Router: circuit-breaker OPEN for model %s — account-specific failure, skipping for this process", key)
        return
    if "invalid_api_key" in msg or "invalid api key" in msg:
        if provider not in _DEAD_PROVIDERS:
            _DEAD_PROVIDERS.add(provider)
            logger.warning("Router: circuit-breaker OPEN for %s — bad credentials, skipping for this process", provider)


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
                # Insert before openrouter / at end
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


# ── Router ────────────────────────────────────────────────────────────────────

class ModelRouter:
    """
    Try each model in FALLBACK_CHAIN until one succeeds or all are exhausted.

    Returns (response_text, provider_name).
    Raises core.errors.LLMUnavailable if every model fails.
    """

    def __init__(self) -> None:
        self._last_provider: Optional[str] = None

    async def call(
        self,
        prompt: str,
        task_type: str = "code_generation",
        system: Optional[str] = None,
        max_tokens: int = 8192,
        trace_name: Optional[str] = None,
        enforce_local: bool = False,
        org_id: Optional[str] = None,
        plan: Optional[str] = None,
    ) -> Tuple[str, str, str]:
        """
        Execute the fallback chain and return (text, provider, model).
        """
        global _active_model, _fallback_count_today, _fallback_date
        from aether_os.core.errors import LLMUnavailable
        from aether_os.core.telemetry.langsmith_tracer import trace_call

        # ── 1. Semantic cache check ───────────────────────────────────────────
        if not enforce_local:
            try:
                from aether_os.core.llm.cache import get_llm_cache
                _llm_cache = get_llm_cache()
                cached = await _llm_cache.get(prompt, task_type, system, org_id=org_id)
                if cached is not None:
                    logger.info("Router: cache HIT task=%s (skipping LLM call)", task_type)
                    self._last_provider = "cache"
                    _active_model = "cache"
                    # Record zero-cost usage
                    if org_id:
                        try:
                            from aether_os.core.llm.budget import get_budget_manager
                            await get_budget_manager().record_usage(
                                org_id=org_id, input_tokens=0, output_tokens=0,
                                model="cache", cache_hit=True,
                            )
                        except Exception:
                            pass
                    return cached, "cache", "cache"
            except Exception as _ce:
                logger.debug("Cache check failed (continuing): %s", _ce)

        # ── 2. Token budget check ─────────────────────────────────────────────
        _recommended_model: Optional[str] = None
        if org_id and plan and not enforce_local:
            try:
                from aether_os.core.llm.budget import get_budget_manager
                _bm = get_budget_manager()
                allowed, reason, _recommended_model = await _bm.check_budget(
                    org_id=org_id, plan=plan
                )
                if not allowed:
                    raise LLMUnavailable(f"Token budget exceeded: {reason}")
                if _recommended_model == "haiku":
                    logger.info("Router: budget downgrade → Haiku (%s)", reason)
            except LLMUnavailable:
                raise
            except Exception as _be:
                logger.debug("Budget check failed (continuing): %s", _be)

        # Reset daily fallback counter on calendar-day boundary
        today = time.strftime("%Y-%m-%d")
        if today != _fallback_date:
            _fallback_count_today = 0
            _fallback_date = today

        # Build trace name from pipeline context vars if not supplied
        if trace_name is None:
            try:
                from aether_os.orchestrator.events import ACTIVE_PHASE, ACTIVE_RUN_ID
                phase = ACTIVE_PHASE.get() or "unknown_phase"
                run_id = (ACTIVE_RUN_ID.get() or "no-run")[:8]
                trace_name = f"{phase}_{run_id}_{task_type}"
            except Exception:
                trace_name = f"llm_{task_type}"

        errors: List[str] = []
        models_tried = 0

        chain = get_fallback_chain()
        if enforce_local:
            chain = [s for s in chain if s.provider == "ollama"]

        # ── Org-specific provider overrides (DB takes precedence over env) ────
        if org_id and not enforce_local:
            chain = await _apply_org_chain_overrides(chain, org_id)

        # ── 3. Plan-based model enforcement (P10) ─────────────────────────────
        if plan == "trial" and not enforce_local:
            # Filter chain to only include free-tier models
            filtered_chain = []
            for spec in chain:
                is_free = False
                if spec.provider == "openrouter" and spec.model.endswith(":free"):
                    is_free = True
                elif spec.provider == "gemini" and "flash" in spec.model.lower():
                    is_free = True
                elif spec.provider == "anthropic" and "haiku" in spec.model.lower():
                    is_free = True
                elif spec.provider == "ollama":
                    is_free = True
                
                if is_free:
                    filtered_chain.append(spec)
            
            if not filtered_chain:
                raise LLMUnavailable("Trial plan users are restricted to free-tier models. No free models available in fallback chain.")
            chain = filtered_chain

        for spec in chain:
            if not _is_provider_configured(spec):
                logger.debug("Router: skipping %s — not configured", spec.provider)
                continue
            if spec.provider in _DEAD_PROVIDERS:
                logger.debug("Router: skipping %s — circuit-breaker open (permanent failure)", spec.provider)
                continue
            if f"{spec.provider}/{spec.model}" in _DEAD_MODELS:
                logger.debug("Router: skipping %s/%s — model-specific circuit-breaker open", spec.provider, spec.model)
                continue

            # Every model after the first one is a fallback
            if models_tried > 0:
                _fallback_count_today += 1
                # Shorter wait between OpenRouter free-tier models (5s); longer
                # for provider switches (10s). Hard errors need no wait at all.
                _wait = 5 if spec.provider == "openrouter" else 10
                if error_class == "fallback":
                    _wait = 0  # hard failure → no cooldown, switch immediately
                logger.info(
                    "Router: falling back to %s/%s (fallbacks today: %d) — waiting %ds",
                    spec.provider, spec.model, _fallback_count_today, _wait,
                )
                if _wait > 0:
                    await asyncio.sleep(_wait)

            models_tried += 1
            error_class = "fallback"  # default if no attempt completes

            _active_prompt = prompt  # augmented with self-critique on placeholder retry
            for attempt in range(spec.retry_count):
                try:
                    async with trace_call(
                        name=trace_name,
                        inputs={
                            "prompt": _active_prompt[:400],
                            "model": spec.model,
                            "provider": spec.provider,
                            "task_type": task_type,
                            "attempt": attempt + 1,
                        },
                    ):
                        result = await asyncio.wait_for(
                            self._call_provider(spec, _active_prompt, task_type, system, max_tokens),
                            timeout=spec.timeout_seconds,
                        )

                    # ── Success ──────────────────────────────────────────────
                    _active_model = f"{spec.provider}/{spec.model}"
                    self._last_provider = spec.provider
                    logger.info(
                        "Router: request served by %s/%s [attempt %d/%d, task=%s]",
                        spec.provider, spec.model,
                        attempt + 1, spec.retry_count, task_type,
                    )
                    # Store in semantic cache (background, non-blocking)
                    if not enforce_local:
                        try:
                            from aether_os.core.llm.cache import get_llm_cache
                            _ct = asyncio.create_task(
                                get_llm_cache().set(prompt, task_type, result, system, org_id=org_id)
                            )
                            _background_tasks.add(_ct)
                            _ct.add_done_callback(_background_tasks.discard)
                        except Exception as exc:
                            logger.debug("LLM semantic cache set failed (non-fatal): %s", exc)
                    # Record token usage for budget tracking (approximate)
                    _est_input = len(_active_prompt) // 4
                    _est_output = len(result) // 4
                    if org_id:
                        try:
                            from aether_os.core.llm.budget import get_budget_manager
                            _ct2 = asyncio.create_task(
                                get_budget_manager().record_usage(
                                    org_id=org_id,
                                    input_tokens=_est_input,
                                    output_tokens=_est_output,
                                    model=spec.model,
                                    cache_hit=False,
                                )
                            )
                            _background_tasks.add(_ct2)
                            _ct2.add_done_callback(_background_tasks.discard)
                        except Exception as exc:
                            logger.debug("Budget token record failed (non-fatal): %s", exc)
                    # Record cost to billing ledger using active run context vars
                    try:
                        from aether_os.orchestrator.events import ACTIVE_RUN_ID, ACTIVE_PHASE, ACTIVE_ORG_ID
                        _run_id = ACTIVE_RUN_ID.get(None)
                        _phase = ACTIVE_PHASE.get("unknown")
                        if _run_id:
                            _COST_PER_1M = {
                                "anthropic":  (3.0, 15.0),
                                "gemini":     (0.35, 1.05),
                                "ollama":     (0.0, 0.0),
                                "openrouter": (0.5, 1.5),
                            }
                            _in_rate, _out_rate = _COST_PER_1M.get(spec.provider, (0.5, 1.5))
                            _cost_usd = (_est_input * _in_rate + _est_output * _out_rate) / 1_000_000
                            # Write to LLMCallRecord (per-run billing detail)
                            from aether_os.core.billing import get_billing_tracker
                            
                            # Get org_id from context or environment
                            _org_id = ACTIVE_ORG_ID.get("") or os.environ.get("ACTIVE_ORG_ID", "-")
                            
                            _ct3 = asyncio.create_task(
                                get_billing_tracker()._async_record_llm_call(
                                    org_id=_org_id,
                                    project_id=_run_id,
                                    phase=_phase,
                                    model=f"{spec.provider}/{spec.model}",
                                    input_tokens=_est_input,
                                    output_tokens=_est_output,
                                    cost_usd=_cost_usd,
                                )
                            )
                            _background_tasks.add(_ct3)
                            _ct3.add_done_callback(_background_tasks.discard)
                            # Also write to TokenBudgetRecord (org-level dashboard stats)
                            if not org_id:
                                # Resolve org_id from run record
                                try:
                                    from aether_os.core.db import get_session_factory as _gsf_mr
                                    from aether_os.core.models import Run as _Run_mr
                                    from sqlalchemy import select as _sel_mr
                                    async def _get_org():
                                        async with _gsf_mr()() as _s:
                                            r = await _s.execute(_sel_mr(_Run_mr.org_id).where(_Run_mr.id == _run_id))
                                            return r.scalar_one_or_none()
                                    _resolved_org = await _get_org()
                                except Exception as exc:
                                    logger.debug("Org ID resolve from run failed: %s", exc)
                                    _resolved_org = None
                            else:
                                _resolved_org = org_id
                            if _resolved_org:
                                from aether_os.core.llm.budget import get_budget_manager
                                _ct4 = asyncio.create_task(
                                    get_budget_manager().record_usage(
                                        org_id=_resolved_org,
                                        input_tokens=_est_input,
                                        output_tokens=_est_output,
                                        model=spec.model,
                                        cache_hit=False,
                                    )
                                )
                                _background_tasks.add(_ct4)
                                _ct4.add_done_callback(_background_tasks.discard)
                    except Exception as exc:
                        logger.debug("Billing ledger record failed (non-fatal): %s", exc)
                    # ── Placeholder guard ────────────────────────────────────
                    # Reject only outputs that look like the model gave up
                    # ("...", "TODO", bare whitespace). Earlier versions had
                    # `len(stripped) < 10` which rejected legitimate short
                    # replies like "OK" or `{"x":1}`. The new rule rejects empty
                    # output or known refusal/template tokens, nothing else.
                    _stripped = result.strip()
                    _PLACEHOLDER_PATTERNS = {
                        "...", "…", "todo", "n/a", "none", "null",
                        "[code here]", "[insert code]", "[your code here]",
                        "# todo", "// todo",
                    }
                    _is_placeholder = (
                        len(_stripped) == 0  # truly empty
                        or _stripped.lower() in _PLACEHOLDER_PATTERNS
                        or (_stripped.endswith("...") and len(_stripped) < 30)
                    )
                    if _is_placeholder:
                        msg = (
                            f"{spec.provider}/{spec.model} returned placeholder "
                            f"response (len={len(_stripped)}): {_stripped[:80]!r}"
                        )
                        logger.warning("Router: %s — will retry with self-critique", msg)
                        errors.append(msg)
                        error_class = "retry"
                        if attempt < spec.retry_count - 1:
                            # Inject self-critique so the next attempt gets context
                            # that its previous response was rejected
                            _active_prompt = (
                                "Your previous response was rejected as a placeholder "
                                "(returned '...', 'TODO', or template text). "
                                "Do NOT return stubs, comments-only, or incomplete code. "
                                "Provide a complete, working implementation.\n\n"
                                + prompt
                            )
                            await asyncio.sleep(1.5 ** attempt)
                        continue
                    # ─────────────────────────────────────────────────────────
                    return result, spec.provider, spec.model

                except asyncio.TimeoutError:
                    msg = f"{spec.provider}/{spec.model} timed out after {spec.timeout_seconds}s"
                    logger.warning("Router: %s", msg)
                    errors.append(msg)
                    error_class = "fallback"   # timeout → skip to next tier
                    break

                except Exception as exc:
                    msg = f"{spec.provider}/{spec.model} attempt {attempt + 1}: {exc}"
                    logger.warning("Router: %s", msg)
                    errors.append(msg)
                    error_class = _classify_error(exc)
                    # Open circuit breaker for permanent failures (bad key, no payment)
                    if error_class == "fallback":
                        _mark_provider_dead(spec.provider, exc, model=spec.model)
                    # For OpenRouter free-tier, a rate-limit on one model won't
                    # clear in 1-2 seconds — skip immediately to the next model.
                    if spec.provider == "openrouter" and error_class == "retry":
                        error_class = "fallback"

                if error_class == "fallback":
                    break  # don't retry, move to next model in chain

                # Transient error — wait before retrying same model
                if attempt < spec.retry_count - 1:
                    backoff = 1.5 ** attempt   # 1 s, 1.5 s
                    await asyncio.sleep(backoff)

        raise LLMUnavailable(
            "All models in the fallback chain exhausted. "
            f"Last errors: {'; '.join(errors[-3:])}"
        )

    async def _call_provider(
        self,
        spec: ModelSpec,
        prompt: str,
        task_type: str,
        system: Optional[str],
        max_tokens: int,
    ) -> str:
        """
        Delegate to the appropriate provider function in core.llm.client.

        We import the module (not the function) so that test patches on
        aether_os.core.llm.client._call_* are picked up correctly.
        """
        import aether_os.core.llm.client as _llm_mod

        if spec.provider == "anthropic":
            client = _llm_mod._get_anthropic_client()
            return await _llm_mod._call_anthropic(
                client, prompt, task_type, system=system, max_tokens=max_tokens
            )
        if spec.provider == "bedrock":
            return await _llm_mod._call_bedrock(
                prompt, task_type, system=system, max_tokens=max_tokens,
                model_id=spec.model,
            )
        if spec.provider == "gemini":
            return await _llm_mod._call_gemini(
                prompt, task_type, system=system, max_tokens=max_tokens
            )
        if spec.provider == "openrouter":
            from aether_os.core.llm.openrouter_client import call_openrouter
            return await call_openrouter(
                prompt, task_type, system=system, max_tokens=max_tokens,
                model=spec.model,
            )
        if spec.provider == "ollama":
            return await _llm_mod._call_ollama_with_model(prompt, task_type, spec.model)

        raise RuntimeError(f"ModelRouter: unknown provider '{spec.provider}'")

    def get_status(self) -> Dict[str, Any]:
        """Return routing stats for the /health and /system/health endpoints."""
        chain = get_fallback_chain()
        return {
            "active_model": _active_model,
            "fallback_count_today": _fallback_count_today,
            "fallback_chain": [f"{s.provider}/{s.model}" for s in chain],
            "model_availability": {
                spec.provider: _is_provider_configured(spec)
                for spec in chain
            },
        }

    @property
    def last_provider(self) -> Optional[str]:
        return self._last_provider


# ── Singleton ─────────────────────────────────────────────────────────────────

_router_instance: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    """Return the process-level ModelRouter singleton."""
    global _router_instance
    if _router_instance is None:
        _router_instance = ModelRouter()
    return _router_instance
