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


# Canonical fallback chain — order is authoritative
FALLBACK_CHAIN: List[ModelSpec] = [
    ModelSpec("anthropic", "claude-sonnet-4-6", 30, 2),
    ModelSpec("gemini",    "gemini-2.5-flash",  45, 2),
    ModelSpec("ollama",    "qwen2.5-coder:3b",  90, 2),
]

# Error-message substrings → retry (transient, worth retrying same model)
_RETRY_PATTERNS = ("rate limit", "429", "overloaded", "server error", "503", "502")
# Error-message substrings → fallback (hard failure, skip to next model)
_FALLBACK_PATTERNS = (
    "api key", "authentication", "invalid_api_key", "unauthorized",
    "not installed", "model not found", "no such model",
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


def _is_provider_configured(spec: ModelSpec) -> bool:
    """Return True if the provider has usable credentials / can be reached."""
    if spec.provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if spec.provider == "gemini":
        key = os.environ.get("GOOGLE_API_KEY", "").strip()
        return bool(key) and key != "REPLACE_WITH_YOUR_GEMINI_KEY"
    # Ollama: always attempt — will fail at call time if not running
    return True


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
    ) -> Tuple[str, str]:
        """
        Execute the fallback chain and return (text, provider).

        trace_name is used as the LangSmith run name.  When omitted it is
        auto-built from ACTIVE_PHASE + ACTIVE_RUN_ID context vars.
        """
        global _active_model, _fallback_count_today, _fallback_date
        from aether_os.core.errors import LLMUnavailable
        from aether_os.core.telemetry.langsmith_tracer import trace_call

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

        for spec in FALLBACK_CHAIN:
            if not _is_provider_configured(spec):
                logger.debug("Router: skipping %s — not configured", spec.provider)
                continue

            # Every model after the first one is a fallback
            if models_tried > 0:
                _fallback_count_today += 1
                logger.info(
                    "Router: falling back to %s/%s (fallbacks today: %d)",
                    spec.provider, spec.model, _fallback_count_today,
                )

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
        if spec.provider == "gemini":
            return await _llm_mod._call_gemini(
                prompt, task_type, system=system, max_tokens=max_tokens
            )
        if spec.provider == "ollama":
            return await _llm_mod._call_ollama_with_model(prompt, task_type, spec.model)

        raise RuntimeError(f"ModelRouter: unknown provider '{spec.provider}'")

    def get_status(self) -> Dict[str, Any]:
        """Return routing stats for the /health and /system/health endpoints."""
        return {
            "active_model": _active_model,
            "fallback_count_today": _fallback_count_today,
            "model_availability": {
                spec.provider: _is_provider_configured(spec)
                for spec in FALLBACK_CHAIN
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
