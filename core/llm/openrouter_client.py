"""
AetherOS — OpenRouter LLM Client

OpenAI-compatible REST API at https://openrouter.ai/api/v1

Free model catalogue (5 free, 2 paid):
  deepseek/deepseek-r1:free          — top-tier reasoning, strong for code
  meta-llama/llama-4-maverick:free   — Llama 4 multimodal, strong reasoning
  meta-llama/llama-4-scout:free      — Llama 4 lightweight, fast for light tasks
  mistralai/mistral-7b-instruct:free — fast, efficient for light tasks
  google/gemma-3-27b-it:free         — balanced free model
  anthropic/claude-3.5-sonnet        — paid, production heavy tasks
  google/gemini-2.5-pro              — paid, advanced reasoning

Task routing:
  Heavy (code_generation, security_scan, testing, architecture, review):
    → OPENROUTER_HEAVY_MODEL (default: deepseek/deepseek-r1:free)
  Light (requirements, documentation, summarize, classify, intake):
    → OPENROUTER_LIGHT_MODEL (default: mistralai/mistral-7b-instruct:free)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_URL = "https://openrouter.ai/api/v1"

OPENROUTER_MODELS = {
    # Free models — copy model ID from openrouter.ai/models
    "minimax-m2.5-free":    "minimax/minimax-m2.5:free",
    "deepseek-r1-free":     "deepseek/deepseek-r1:free",
    "deepseek-v3-free":     "deepseek/deepseek-chat-v3-5:free",
    "llama4-maverick-free": "meta-llama/llama-4-maverick:free",
    "llama4-scout-free":    "meta-llama/llama-4-scout:free",
    "llama33-70b-free":     "meta-llama/llama-3.3-70b-instruct:free",
    "qwen3-235b-free":      "qwen/qwen3-235b-a22b:free",
    "qwen3-30b-free":       "qwen/qwen3-30b-a3b:free",
    "mistral-free":         "mistralai/mistral-7b-instruct:free",
    "gemma3-27b-free":      "google/gemma-3-27b-it:free",
    "gemma3-12b-free":      "google/gemma-3-12b-it:free",
    "phi4-free":            "microsoft/phi-4:free",
    "nemotron-free":        "nvidia/llama-3.1-nemotron-70b-instruct:free",
    # Paid models
    "claude-sonnet-4-6":    "anthropic/claude-sonnet-4-6",
    "claude35-sonnet":      "anthropic/claude-3.5-sonnet",
    "gemini25-pro":         "google/gemini-2.5-pro",
    "gpt4o":                "openai/gpt-4o",
}

_DEFAULT_HEAVY = "deepseek/deepseek-r1:free"
_DEFAULT_LIGHT  = "mistralai/mistral-7b-instruct:free"

_HEAVY_TASKS = {"code_generation", "security_scan", "testing", "architecture", "review"}


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
) -> str:
    """Call OpenRouter via the OpenAI-compatible chat/completions endpoint."""
    import httpx

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    chosen_model = model or select_openrouter_model(task_type)
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
    timeout = float(os.environ.get("OPENROUTER_TIMEOUT", "60"))

    logger.info("LLM call: provider=openrouter model=%s task=%s", chosen_model, task_type)

    async with httpx.AsyncClient(timeout=timeout) as http:
        try:
            resp = await http.post(
                f"{_BASE_URL}/chat/completions",
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
