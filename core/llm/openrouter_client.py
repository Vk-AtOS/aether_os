"""
AetherOS — OpenRouter LLM Client

OpenAI-compatible REST API at https://openrouter.ai/api/v1

Live free model catalogue (verified 2026-06-06 against openrouter.ai/api/v1/models):
  minimax/minimax-m2.5:free                  — best free model for code generation
  meta-llama/llama-3.3-70b-instruct:free     — strong general + code, 128K ctx
  nvidia/nemotron-3-super-120b-a12b:free     — 120B, strong reasoning
  nousresearch/hermes-3-llama-3.1-405b:free  — 405B, very capable
  meta-llama/llama-3.2-3b-instruct:free      — small/fast for light tasks
  google/gemma-3-27b-it:free                 — balanced free model, 262K ctx
  google/gemma-4-31b-it:free                 — 262K ctx, function calling
  poolside/laguna-m.1:free                   — 131K ctx, purpose-built coding agent
  poolside/laguna-xs.2:free                  — 131K ctx, efficient coding agent
  baidu/cobuddy:free                         — 131K ctx, coding + agent workflows
  arcee-ai/trinity-large-thinking:free       — 262K ctx, reasoning + agentic
  google/gemma-4-26b-a4b-it:free             — 262K ctx, near-31B quality

Previously available models that are now 404 (do NOT use):
  deepseek/deepseek-r1:free, deepseek/deepseek-v4-flash:free,
  qwen/qwen3-8b:free, qwen/qwen3-coder:free, qwen/qwen3-235b-a22b:free,
  meta-llama/llama-4-maverick:free, meta-llama/llama-4-scout:free,
  google/gemma-4-27b-it:free, microsoft/phi-4:free,
  mistralai/mistral-7b-instruct:free, nvidia/llama-3.1-nemotron-70b-instruct:free

Task routing:
  Heavy (code_generation, security_scan, testing, architecture, review):
    → OPENROUTER_HEAVY_MODEL (default: minimax/minimax-m2.5:free)
  Light (requirements, documentation, summarize, classify, intake):
    → OPENROUTER_LIGHT_MODEL (default: meta-llama/llama-3.3-70b-instruct:free)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from aether_os.core.api_key_store import get_api_key
from aether_os.core.llm._org_context import _current_org_id

logger = logging.getLogger(__name__)

_BASE_URL = "https://openrouter.ai/api/v1"


def base_url() -> str:
    """OpenAI-compatible endpoint. OPENROUTER_BASE_URL points the same client at another provider with the same API,
    e.g. NVIDIA's https://integrate.api.nvidia.com/v1 (free developer tier) when no paid model provider is available."""
    return os.environ.get("OPENROUTER_BASE_URL", "").strip().rstrip("/") or _BASE_URL

OPENROUTER_MODELS = {
    # ── Free models (verified available 2026-06-06) ───────────────────────
    "minimax-m2.5-free":      "minimax/minimax-m2.5:free",
    "llama33-70b-free":       "meta-llama/llama-3.3-70b-instruct:free",
    "llama32-3b-free":        "meta-llama/llama-3.2-3b-instruct:free",
    "nemotron-super-120b":    "nvidia/nemotron-3-super-120b-a12b:free",
    "nemotron-nano-9b":       "nvidia/nemotron-nano-9b-v2:free",
    "hermes3-405b-free":      "nousresearch/hermes-3-llama-3.1-405b:free",
    "gemma3-27b-free":        "google/gemma-3-27b-it:free",
    "gemma4-31b-free":        "google/gemma-4-31b-it:free",
    "gemma4-26b-free":        "google/gemma-4-26b-a4b-it:free",
    "gpt-oss-120b-free":      "openai/gpt-oss-120b:free",
    "gpt-oss-20b-free":       "openai/gpt-oss-20b:free",
    # ── Coding-specialist free models (large context, code-optimised) ─────
    "laguna-m1-free":         "poolside/laguna-m.1:free",
    "laguna-xs2-free":        "poolside/laguna-xs.2:free",
    "cobuddy-free":           "baidu/cobuddy:free",
    "trinity-thinking-free":  "arcee-ai/trinity-large-thinking:free",
    # ── Paid models ───────────────────────────────────────────────────────
    "claude-sonnet-4-6":      "anthropic/claude-sonnet-4-6",
    "claude35-sonnet":        "anthropic/claude-3.5-sonnet",
    "gemini25-pro":           "google/gemini-2.5-pro",
    "gpt4o":                  "openai/gpt-4o",
}

# Council uses a diverse set of models — different from the pipeline primary
# so council reviews are genuinely independent.  Ordered by preference; the
# council tries each in turn, skipping any that return 429/404.
_DEFAULT_COUNCIL_MODELS = [
    "poolside/laguna-m.1:free",                 # 131K ctx, coding specialist
    "meta-llama/llama-3.3-70b-instruct:free",   # reliable, 128K ctx
    "google/gemma-4-31b-it:free",               # 262K ctx, balanced
    "arcee-ai/trinity-large-thinking:free",     # 262K ctx, reasoning + agentic
    "nousresearch/hermes-3-llama-3.1-405b:free", # 405B, highly capable
    "minimax/minimax-m2.5:free",                # best free for code
]
# OPENROUTER_COUNCIL_MODELS (comma-separated) replaces the list: with OPENROUTER_BASE_URL set, the OpenRouter names
# above do not exist on the other endpoint and every council call would fail.
COUNCIL_MODELS = [m.strip() for m in os.environ.get("OPENROUTER_COUNCIL_MODELS", "").split(",") if m.strip()] \
    or _DEFAULT_COUNCIL_MODELS

_DEFAULT_HEAVY = "minimax/minimax-m2.5:free"
_DEFAULT_LIGHT  = "meta-llama/llama-3.3-70b-instruct:free"

_HEAVY_TASKS = {"code_generation", "security_scan", "architecture", "review"}
# Note: "testing" removed — test scaffolding uses light model to reduce 429s on free tier


def select_openrouter_model(task_type: str) -> str:
    """Return the best OpenRouter model identifier for the given task type."""
    if task_type in _HEAVY_TASKS:
        return os.environ.get("OPENROUTER_HEAVY_MODEL", _DEFAULT_HEAVY)
    return os.environ.get("OPENROUTER_LIGHT_MODEL", _DEFAULT_LIGHT)


async def call_openrouter(
    prompt: str,
    task_type: str = "code_generation",
    system: Optional[str] = None,
    max_tokens: int = 8192,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    """Call OpenRouter via the OpenAI-compatible chat/completions endpoint.

    `api_key`: the caller's key for this call; when omitted it is looked up for
    the org in the current context (falling back to the platform key).
    """
    import httpx
    from aether_os.core.errors import LLMUnavailable
    from aether_os.core.llm import controls
    from aether_os.core.llm.data_policy import effective_level, permits

    # Every OpenRouter call, whoever makes it (router, council, compressor): kill switch and data policy.
    if await controls.global_kill_active():
        raise LLMUnavailable("LLM calls are disabled by the platform kill switch")
    if api_key is None:
        api_key = await get_api_key("openrouter", _current_org_id.get())
    api_key = (api_key or "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not configured for this org or system.")

    chosen_model = model or select_openrouter_model(task_type)
    if not permits("openrouter", chosen_model, effective_level(None, prompt, system or "")):
        raise LLMUnavailable("This data may not be sent to OpenRouter (restricted data, or community models not enabled)")
    system_content = system or (
        "You are AetherOS, an expert autonomous software development system. "
        "Provide precise, production-quality responses."
    )

    payload = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://aetheros.dev",
        "X-Title": "AetherOS",
    }
    timeout = float(os.environ.get("OPENROUTER_TIMEOUT", "25"))

    logger.info("LLM call: provider=openrouter model=%s task=%s", chosen_model, task_type)

    async with httpx.AsyncClient(timeout=timeout) as http:
        try:
            resp = await http.post(
                f"{base_url()}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"OpenRouter {chosen_model} HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"OpenRouter call failed with {chosen_model}: {exc}"
            ) from exc
