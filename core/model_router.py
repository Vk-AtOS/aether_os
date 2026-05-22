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
    "minimax/minimax-m2.5:free,"
    "meta-llama/llama-3.3-70b-instruct:free,"
    "qwen/qwen3-8b:free,"
    "nvidia/nemotron-3-super-120b-a12b:free,"
    "deepseek/deepseek-v4-flash:free,"
    "nousresearch/hermes-3-llama-3.1-405b:free,"
    "meta-llama/llama-3.2-3b-instruct:free"
)


def _is_provider_configured(spec: ModelSpec) -> bool:
    """Return True if the provider has usable credentials / can be reached."""
    if spec.provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if spec.provider == "gemini":
        key = os.environ.get("GOOGLE_API_KEY", "").strip()
        return bool(key) and key != "REPLACE_WITH_YOUR_GEMINI_KEY"
    if spec.provider == "openrouter":
        return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    if spec.provider == "bedrock":
        # BEDROCK_ENABLED must be explicitly set to "true" — payment instrument required
        # for cross-region inference profiles. Credentials alone are not sufficient.
        if os.environ.get("BEDROCK_ENABLED", "false").lower() != "true":
            return False
        return bool(
            os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
            and os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
        )
    # Ollama: always attempt — will fail at call time if not running
    return True


def get_fallback_chain() -> List[ModelSpec]:
    """Build fallback chain from environment.  Re-called on every request so
    settings changes take effect immediately without a server restart.

    When OFFLINE_MODE=true the chain is restricted to Ollama only, bypassing
    all cloud providers.  This is the correct setting for air-gapped deployments
    (government, hospitals, banks) where no outbound internet is available.
    """
    # ── Air-gapped / offline mode ─────────────────────────────────────────────
    if os.environ.get("OFFLINE_MODE", "").lower() == "true":
        ollama_model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        ollama_timeout = int(os.environ.get("OLLAMA_TIMEOUT", "300"))
        logger.info(
            "OFFLINE_MODE=true — restricting LLM chain to Ollama only (model=%s)",
            ollama_model,
        )
        return [ModelSpec("ollama", ollama_model, ollama_timeout, 2)]

    primary = os.environ.get("PRIMARY_LLM", "anthropic").lower()
    anthropic_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    ollama_model = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:3b")
    ollama_timeout = int(os.environ.get("OLLAMA_TIMEOUT", "120"))

    # Ordered list of OpenRouter models to cycle through on rate-limit
    fallback_env = os.environ.get("OPENROUTER_FALLBACK_MODELS", "").strip()
    if fallback_env:
        openrouter_models = [m.strip() for m in fallback_env.split(",") if m.strip()]
    else:
        # Fall back to individual heavy/light env vars, then built-in defaults
        heavy = os.environ.get("OPENROUTER_HEAVY_MODEL", "minimax/minimax-m2.5:free")
        defaults = [m.strip() for m in _DEFAULT_FALLBACK_MODELS.split(",")]
        openrouter_models = list(dict.fromkeys([heavy] + defaults))  # dedup, preserve order

    bedrock_model = os.environ.get("BEDROCK_MODEL", "anthropic.claude-3-5-haiku-20241022-v1:0")
    non_openrouter = {
        "anthropic": ModelSpec("anthropic", anthropic_model, 30, 2),
        "bedrock":   ModelSpec("bedrock",   bedrock_model,   45, 2),
        "gemini":    ModelSpec("gemini",    "gemini-2.5-flash", 45, 2),
        "ollama":    ModelSpec("ollama",    ollama_model, ollama_timeout, 1),
    }

    chain: List[ModelSpec] = []

    if primary in non_openrouter:
        chain.append(non_openrouter[primary])

    if primary == "openrouter":
        # OpenRouter is primary — put all its models first
        for m in openrouter_models:
            chain.append(ModelSpec("openrouter", m, 60, 2))
        for p in ("anthropic", "bedrock", "gemini", "ollama"):
            if p != primary and _is_provider_configured(non_openrouter[p]):
                chain.append(non_openrouter[p])
    else:
        # Non-OpenRouter primary — cloud providers first, then OpenRouter, then Ollama
        for p in ("anthropic", "bedrock", "gemini"):
            if p != primary and _is_provider_configured(non_openrouter[p]):
                chain.append(non_openrouter[p])
        for m in openrouter_models:
            chain.append(ModelSpec("openrouter", m, 60, 2))
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
    ) -> Tuple[str, str]:
        """
        Execute the fallback chain and return (text, provider).

        Cost reduction layers applied in order:
          1. Semantic cache check (skips LLM entirely if hit)
          2. Token budget check (downgrades model or blocks on trial plan)
          3. Anthropic prompt caching (via cache_control on system prompt)
          4. Normal fallback chain
          5. Record usage for budget tracking

        trace_name is used as the LangSmith run name.  When omitted it is
        auto-built from ACTIVE_PHASE + ACTIVE_RUN_ID context vars.
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
                    return cached, "cache"
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

        for spec in chain:
            if not _is_provider_configured(spec):
                logger.debug("Router: skipping %s — not configured", spec.provider)
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

            for attempt in range(spec.retry_count):
                try:
                    async with trace_call(
                        name=trace_name,
                        inputs={
                            "prompt": prompt[:400],
                            "model": spec.model,
                            "provider": spec.provider,
                            "task_type": task_type,
                            "attempt": attempt + 1,
                        },
                    ):
                        result = await asyncio.wait_for(
                            self._call_provider(spec, prompt, task_type, system, max_tokens),
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
                            asyncio.create_task(
                                get_llm_cache().set(prompt, task_type, result, system, org_id=org_id)
                            )
                        except Exception:
                            pass
                    # Record token usage for budget tracking (approximate)
                    _est_input = len(prompt) // 4
                    _est_output = len(result) // 4
                    if org_id:
                        try:
                            from aether_os.core.llm.budget import get_budget_manager
                            asyncio.create_task(
                                get_budget_manager().record_usage(
                                    org_id=org_id,
                                    input_tokens=_est_input,
                                    output_tokens=_est_output,
                                    model=spec.model,
                                    cache_hit=False,
                                )
                            )
                        except Exception:
                            pass
                    # Record cost to billing ledger using active run context vars
                    try:
                        from aether_os.orchestrator.events import ACTIVE_RUN_ID, ACTIVE_PHASE
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
                            asyncio.create_task(
                                get_billing_tracker()._async_record_llm_call(
                                    project_id=_run_id,
                                    phase=_phase,
                                    model=f"{spec.provider}/{spec.model}",
                                    input_tokens=_est_input,
                                    output_tokens=_est_output,
                                    cost_usd=_cost_usd,
                                )
                            )
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
                                except Exception:
                                    _resolved_org = None
                            else:
                                _resolved_org = org_id
                            if _resolved_org:
                                from aether_os.core.llm.budget import get_budget_manager
                                asyncio.create_task(
                                    get_budget_manager().record_usage(
                                        org_id=_resolved_org,
                                        input_tokens=_est_input,
                                        output_tokens=_est_output,
                                        model=spec.model,
                                        cache_hit=False,
                                    )
                                )
                    except Exception:
                        pass
                    # ── Placeholder guard ────────────────────────────────────
                    # Some models return "...", "TODO", bare whitespace, or
                    # near-empty strings when they hit context limits or refuse
                    # the task. These are treated as transient failures so we
                    # retry the same model then fall back to the next tier.
                    _stripped = result.strip()
                    _PLACEHOLDER_PATTERNS = {
                        "...", "…", "todo", "n/a", "none", "null",
                        "[code here]", "[insert code]", "[your code here]",
                        "# TODO", "# todo",
                    }
                    _is_placeholder = (
                        len(_stripped) < 50
                        or _stripped.lower() in _PLACEHOLDER_PATTERNS
                        or _stripped in {"...", "…"}
                        or (_stripped.endswith("...") and len(_stripped) < 120)
                    )
                    if _is_placeholder:
                        msg = (
                            f"{spec.provider}/{spec.model} returned placeholder "
                            f"response (len={len(_stripped)}): {_stripped[:80]!r}"
                        )
                        logger.warning("Router: %s — will retry", msg)
                        errors.append(msg)
                        error_class = "retry"
                        if attempt < spec.retry_count - 1:
                            await asyncio.sleep(1.5 ** attempt)
                        continue
                    # ─────────────────────────────────────────────────────────
                    return result, spec.provider

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
            return await _llm_mod._call_anthropic(
                prompt, task_type, system=system, max_tokens=max_tokens
            )
        if spec.provider == "bedrock":
            return await _llm_mod._call_bedrock(
                prompt, task_type, system=system, max_tokens=max_tokens
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
