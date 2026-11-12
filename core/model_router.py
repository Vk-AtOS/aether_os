"""
AetherOS — Multi-Model Router
==============================
Fallback chain (in priority order):
  1. Anthropic  claude-sonnet-4-6   — 30 s timeout, 2 retries
  2. Gemini     gemini-2.5-flash    — 45 s timeout, 2 retries
  3. Ollama     qwen2.5-coder:3b    — 90 s timeout, 2 retries

Each provider is skipped if its credentials are absent.
Retry vs fallback decision is based on error-message classification:
  retry    — transient (rate limit, 429, server overload)
  fallback — hard failure (bad key, SDK missing, model not found)

Provider chain logic lives in model_router_providers.py.
Which model served each request is logged at INFO level and visible
in LangSmith traces (phase_name + run_id).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from aether_os.core.model_router_providers import (
    ModelSpec,
    get_fallback_chain,
    _is_provider_configured,
    _classify_error,
    _mark_provider_dead,
    _is_provider_dead,
    PLATFORM_SCOPE,
    _apply_org_chain_overrides,
    _DEAD_PROVIDERS,
    _DEAD_MODELS,
    FALLBACK_CHAIN,
)
from aether_os.core.api_key_store import get_api_key
from aether_os.core.llm._org_context import _current_org_id
from aether_os.core.llm.ahm import default_ahm as _ahm
from aether_os.orchestrator.events import ACTIVE_PHASE, ACTIVE_RUN_ID, ACTIVE_ORG_ID

logger = logging.getLogger(__name__)

# Strong references prevent GC from silently killing background tasks
_background_tasks: set = set()

# ── Module-level stats (reset on process restart) ─────────────────────────────
_active_model: Optional[str] = None        # e.g. "anthropic/claude-sonnet-4-6"
_fallback_count_today: int = 0
_fallback_date: str = ""


# Router provider name → api_key_store provider name (bedrock/ollama have no API key).
_KEY_PROVIDERS = {"anthropic": "anthropic", "gemini": "google", "openrouter": "openrouter"}


async def _provider_key(provider: str, org_id: Optional[str]) -> Optional[str]:
    """This org's key for the provider, else the platform key, else None.

    Resolved per call and passed to the provider client explicitly — an org's key
    is never read from (or written to) the process environment.
    """
    name = _KEY_PROVIDERS.get(provider)
    if name is None:
        return None
    return await get_api_key(name, org_id or _current_org_id.get())


async def _breaker_scope(provider: str, org_id: Optional[str], api_key: Optional[str]) -> str:
    """Whose credentials this call uses: the org id for the org's own key, else the platform.

    A failure of an org's own key must only open the breaker for that org.
    """
    name = _KEY_PROVIDERS.get(provider)
    org = org_id or _current_org_id.get()
    if not (name and org and api_key) or api_key == await get_api_key(name, None):
        return PLATFORM_SCOPE
    return org


def _get_ahm():
    """Return the AHM singleton. Kept as a function so tests can patch it and
    call sites don't need to change if the import ever needs to become lazy again."""
    return _ahm


# ── Router ────────────────────────────────────────────────────────────────────

class ModelRouter:
    """
    Try each model in the fallback chain until one succeeds or all are exhausted.

    Returns (response_text, provider_name).
    Raises core.errors.LLMUnavailable if every model fails.

    The model name used for the last successful call is available via the
    `last_model` property so callers that need it (e.g. LLMClient) can read it
    without requiring a 3-tuple return signature.
    """

    def __init__(self) -> None:
        self._last_provider: Optional[str] = None
        self._last_model: Optional[str] = None

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
        primary_provider: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Execute the fallback chain and return (text, provider).
        The model name is also stored in self._last_model for callers that need it.
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
                        except Exception as exc:
                            logger.debug("Cache-hit zero-cost budget record failed: %s", exc)
                    self._last_model = "cache"
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
                phase = ACTIVE_PHASE.get() or "unknown_phase"
                run_id = (ACTIVE_RUN_ID.get() or "no-run")[:8]
                trace_name = f"{phase}_{run_id}_{task_type}"
            except Exception as exc:
                logger.debug("Trace name resolution failed, using fallback: %s", exc)
                trace_name = f"llm_{task_type}"

        errors: List[str] = []
        models_tried = 0

        chain = get_fallback_chain()
        if enforce_local:
            chain = [s for s in chain if s.provider == "ollama"]

        # ── Caller-pinned provider (ContextVar-safe; avoids os.environ mutation) ──
        if primary_provider is not None and not enforce_local:
            chain = sorted(chain, key=lambda s: 0 if s.provider == primary_provider else 1)

        # ── Org-specific provider overrides (DB takes precedence over env) ────
        if org_id and not enforce_local:
            chain = await _apply_org_chain_overrides(chain, org_id)

        # ── AHM: reorder chain based on runtime health scores ─────────────────
        # Healthy providers (score >= 0.5) stay first; degraded ones move last.
        # Caller-pinned and org overrides above take precedence — AHM only acts
        # on providers that weren't already explicitly sorted above.
        if not enforce_local and primary_provider is None:
            try:
                _ahm_inst = _get_ahm()
                if _ahm_inst:
                    chain = _ahm_inst.reorder_chain(chain)
            except Exception as _ahm_exc:
                logger.debug("AHM reorder failed (non-fatal): %s", _ahm_exc)

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
                raise LLMUnavailable(
                    "Trial plan users are restricted to free-tier models. "
                    "No free models available in fallback chain."
                )
            chain = filtered_chain

        error_class = "fallback"  # default for first iteration
        for spec in chain:
            _api_key = await _provider_key(spec.provider, org_id)
            if not _api_key and not _is_provider_configured(spec):
                logger.debug("Router: skipping %s — not configured", spec.provider)
                continue
            _scope = await _breaker_scope(spec.provider, org_id, _api_key)
            if _is_provider_dead(spec.provider, spec.model, _scope):
                logger.debug("Router: skipping %s/%s — circuit-breaker open (scope=%s)",
                             spec.provider, spec.model, _scope[:8] or "platform")
                continue

            # Every model after the first one is a fallback
            if models_tried > 0:
                _fallback_count_today += 1
                # Shorter wait between OpenRouter free-tier models (5s); longer
                # for provider switches (10s). Hard errors need no wait at all.
                _wait = 5 if spec.provider == "openrouter" else 10
                if error_class == "fallback":
                    _wait = 0  # hard failure → no cooldown, switch immediately
                _log_fn = logger.warning if (primary_provider and spec.provider != primary_provider) else logger.info
                _log_fn(
                    "Router: falling back to %s/%s (fallbacks today: %d, pinned=%s) — waiting %ds",
                    spec.provider, spec.model, _fallback_count_today, primary_provider or "none", _wait,
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
                            self._call_provider(spec, _active_prompt, task_type, system,
                                                max_tokens, api_key=_api_key),
                            timeout=spec.timeout_seconds,
                        )

                    # ── Success ──────────────────────────────────────────────
                    _active_model = f"{spec.provider}/{spec.model}"
                    self._last_provider = spec.provider
                    self._last_model = spec.model
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
                            from aether_os.core.billing import get_billing_tracker
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
                            _active_prompt = (
                                "Your previous response was rejected as a placeholder "
                                "(returned '...', 'TODO', or template text). "
                                "Do NOT return stubs, comments-only, or incomplete code. "
                                "Provide a complete, working implementation.\n\n"
                                + prompt
                            )
                            await asyncio.sleep(1.5 ** attempt)
                        continue
                    # ── AHM: record success ───────────────────────────────────
                    try:
                        _ahm_s = _get_ahm()
                        if _ahm_s:
                            _ahm_s.record_success(spec.provider)
                    except Exception:
                        pass
                    # ─────────────────────────────────────────────────────────
                    return result, spec.provider

                except asyncio.TimeoutError:
                    msg = f"{spec.provider}/{spec.model} timed out after {spec.timeout_seconds}s"
                    logger.warning("Router: %s", msg)
                    errors.append(msg)
                    error_class = "fallback"   # timeout → skip to next tier
                    # ── AHM: record timeout as a failure ─────────────────────
                    try:
                        _ahm_t = _get_ahm()
                        if _ahm_t:
                            _ahm_t.record_failure(spec.provider, f"timeout {spec.timeout_seconds}s")
                    except Exception:
                        pass
                    break

                except Exception as exc:
                    msg = f"{spec.provider}/{spec.model} attempt {attempt + 1}: {exc}"
                    logger.warning("Router: %s", msg)
                    errors.append(msg)
                    error_class = _classify_error(exc)
                    # Open circuit breaker for permanent failures (bad key, no payment)
                    if error_class == "fallback":
                        _mark_provider_dead(spec.provider, exc, model=spec.model, scope=_scope)
                    # ── AHM: record exception as a failure ────────────────────
                    try:
                        _ahm_e = _get_ahm()
                        if _ahm_e:
                            _ahm_e.record_failure(spec.provider, str(exc)[:120])
                    except Exception:
                        pass
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
        api_key: Optional[str] = None,
    ) -> str:
        """
        Delegate to the appropriate provider function in core.llm.client.
        `api_key` is the key resolved for this call's org (see _provider_key).

        We import the module (not the function) so that test patches on
        aether_os.core.llm.client._call_* are picked up correctly.
        """
        import aether_os.core.llm.client as _llm_mod

        if spec.provider == "anthropic":
            return await _llm_mod._call_anthropic(
                prompt, task_type, system=system, max_tokens=max_tokens, api_key=api_key
            )
        if spec.provider == "bedrock":
            return await _llm_mod._call_bedrock(
                prompt, task_type, system=system, max_tokens=max_tokens,
                model_id=spec.model,
            )
        if spec.provider == "gemini":
            return await _llm_mod._call_gemini(
                prompt, task_type, system=system, max_tokens=max_tokens, api_key=api_key
            )
        if spec.provider == "openrouter":
            from aether_os.core.llm.openrouter_client import call_openrouter
            return await call_openrouter(
                prompt, task_type, system=system, max_tokens=max_tokens,
                model=spec.model, api_key=api_key,
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

    @property
    def last_model(self) -> Optional[str]:
        return self._last_model


# ── Singleton ─────────────────────────────────────────────────────────────────

_router_instance: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    """Return the process-level ModelRouter singleton."""
    global _router_instance
    if _router_instance is None:
        _router_instance = ModelRouter()
    return _router_instance
