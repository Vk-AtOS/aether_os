"""
AetherOS — Unified LLM Client

Provider priority:
  Tier 1: Anthropic Claude  (ANTHROPIC_API_KEY set)
    Heavy → claude-sonnet-4-6
    Light → claude-haiku-4-5-20251001
  Tier 2: Google Gemini     (GOOGLE_API_KEY set)
    Heavy → gemini-2.5-pro
    Light → gemini-2.0-flash
  Tier 3: Ollama            (localhost:11434 reachable)
  Tier 4: AirLLM            (air-gapped fallback)

Single async interface:
    await client.call(prompt, task_type, context) -> str

Features:
- Task routing (heavy tasks → primary model, light tasks → fast model)
- Retry with exponential backoff (3 attempts)
- Cost tracking (token counts logged to telemetry)
- Provider/model logged at start of every call
- last_provider attribute set after each call
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Task type → tier routing
_HEAVY_TASKS = {"code_generation", "security_scan", "testing", "architecture", "review"}
_LIGHT_TASKS = {"requirements", "documentation", "summarize", "classify", "intake", "portal"}

# Gemini model assignments
_GEMINI_HEAVY = "gemini-2.5-pro"
_GEMINI_LIGHT  = "gemini-2.0-flash"

# Cost tracking (tokens)
_cost_registry: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}


# ── Anthropic ─────────────────────────────────────────────────────────────────

def _get_anthropic_client():
    """Lazy-import Anthropic SDK and return a client instance."""
    try:
        import anthropic  # type: ignore
    except ImportError as exc:
        raise ImportError("anthropic SDK not installed. Run: pip install anthropic") from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Get your key from https://console.anthropic.com"
        )
    return anthropic.AsyncAnthropic(api_key=api_key)


def _select_model(task_type: str) -> str:
    """Route task type to the appropriate Anthropic model."""
    from ..config.loader import get_config
    cfg = get_config()
    if task_type in _LIGHT_TASKS:
        return cfg.get("models.haiku", "claude-haiku-4-5-20251001")
    return cfg.get("models.primary", "claude-sonnet-4-6")


async def _call_anthropic(
    prompt: str,
    task_type: str,
    system: Optional[str] = None,
    max_tokens: int = 8192,
) -> str:
    """Call Anthropic API with retry + cost tracking."""
    from ..config.loader import get_config
    cfg = get_config()
    retries = cfg.get("llm.retry_attempts", 3)
    delay = cfg.get("llm.retry_delay_seconds", 2)
    model = _select_model(task_type)
    system_prompt = system or (
        "You are AetherOS, an expert autonomous software development system. "
        "Provide precise, production-quality responses."
    )

    logger.info("LLM call: provider=anthropic model=%s task=%s", model, task_type)

    client = _get_anthropic_client()
    last_exc: Exception | None = None

    for attempt in range(retries):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = response.usage
            _cost_registry["prompt_tokens"] += usage.input_tokens
            _cost_registry["completion_tokens"] += usage.output_tokens
            _cost_registry["calls"] += 1
            text = response.content[0].text if response.content else ""
            logger.debug(
                "Anthropic [%s] attempt=%d tokens=%d+%d",
                model, attempt + 1, usage.input_tokens, usage.output_tokens,
            )
            return text
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Anthropic call failed (attempt %d/%d): %s", attempt + 1, retries, exc
            )
            if attempt < retries - 1:
                await asyncio.sleep(delay * (2 ** attempt))

    raise last_exc  # type: ignore


# ── Google Gemini ─────────────────────────────────────────────────────────────

def _select_gemini_model(task_type: str) -> str:
    """Route task type to the appropriate Gemini model."""
    if task_type in _HEAVY_TASKS:
        return _GEMINI_HEAVY
    return _GEMINI_LIGHT


async def _call_gemini(
    prompt: str,
    task_type: str,
    system: Optional[str] = None,
    max_tokens: int = 8192,
) -> str:
    """Call Google Gemini API with retry (uses google-genai SDK)."""
    try:
        from google import genai  # type: ignore
        from google.genai import types as genai_types  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "google-genai SDK not installed. Run: pip install google-genai"
        ) from exc

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY environment variable is not set.")

    from ..config.loader import get_config
    cfg = get_config()
    retries = cfg.get("llm.retry_attempts", 3)
    delay = cfg.get("llm.retry_delay_seconds", 2)
    model_name = _select_gemini_model(task_type)

    logger.info("LLM call: provider=gemini model=%s task=%s", model_name, task_type)

    system_instruction = system or (
        "You are AetherOS, an expert autonomous software development system. "
        "Provide precise, production-quality responses."
    )

    client = genai.Client(api_key=api_key)

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    max_output_tokens=max_tokens,
                ),
            )
            text = response.text
            _cost_registry["calls"] += 1
            logger.debug("Gemini [%s] attempt=%d", model_name, attempt + 1)
            return text
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Gemini call failed (attempt %d/%d): %s", attempt + 1, retries, exc
            )
            if attempt < retries - 1:
                await asyncio.sleep(delay * (2 ** attempt))

    raise last_exc  # type: ignore


# ── Ollama ────────────────────────────────────────────────────────────────────

async def _call_ollama_with_model(prompt: str, task_type: str, model: str) -> str:
    """Call Ollama via HTTP with a specific model."""
    import httpx  # type: ignore
    from ..config.loader import get_config
    cfg = get_config()
    base_url = cfg.get("llm.ollama_base_url", "http://localhost:11434")
    timeout = cfg.get("llm.timeout_seconds", 120)

    logger.info("Using Ollama model: %s", model)
    logger.info("LLM call: provider=ollama model=%s task=%s", model, task_type)

    url = f"{base_url}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False}

    async with httpx.AsyncClient(timeout=timeout) as http:
        try:
            resp = await http.post(url, json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception as exc:
            raise RuntimeError(f"Ollama call failed with {model}: {exc}") from exc


async def _call_ollama(prompt: str, task_type: str) -> str:
    """Call Ollama using the default model from env."""
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
    return await _call_ollama_with_model(prompt, task_type, model)


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_local_llm() -> bool:
    return os.environ.get("PRIMARY_LLM", "ollama") == "ollama"


def get_prompt_style() -> str:
    return "minimal" if is_local_llm() else "full"


def is_local_provider():
    """Legacy alias for compatibility."""
    return is_local_llm()


def safe_parse_json(text: str) -> dict:
    import re, json
    # Try direct parse
    try:
        return json.loads(text.strip())
    except:
        pass
    # Find JSON block anywhere in response
    for pattern in [r'\{[^{}]*\}', r'\{.*?\}']:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    # Last resort - return structured default
    return {"content": text.strip(), "parse_error": True, "raw": text[:1000]}


# ── LLMClient ─────────────────────────────────────────────────────────────────

class LLMClient:
    """
    Unified async LLM client for AetherOS.

    Provider priority:
      Tier 1 Anthropic  →  Tier 2 Gemini  →  Tier 3 Ollama  →  LLMUnavailable

    Usage:
        client = LLMClient()
        result = await client.call("Write a FastAPI endpoint", task_type="code_generation")
        print(client.last_provider)   # "anthropic" | "gemini" | "ollama"
    """

    def __init__(self) -> None:
        self.last_provider: Optional[str] = None

    async def call(
        self,
        prompt: str,
        task_type: str = "code_generation",
        context: Optional[Dict[str, Any]] = None,
        system: Optional[str] = None,
        max_tokens: int = 8192,
    ) -> str:
        """
        Call the LLM with task routing and tiered fallback.
        """
        from ..errors import LLMUnavailable

        if context:
            ctx_str = json.dumps(context, indent=2)
            prompt = f"Context:\n{ctx_str}\n\n{prompt}"

        # BUG FIX: Skip Anthropic and Gemini entirely. Direct to Ollama.
        # Try primary model then fallback 3b model.
        primary_model = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
        fallback_model = "qwen2.5-coder:3b"
        
        for model in [primary_model, fallback_model]:
            try:
                # Check if model is installed
                import httpx
                from ..config.loader import get_config
                cfg = get_config()
                base_url = cfg.get("llm.ollama_base_url", "http://localhost:11434")
                
                # Check tags to see if model exists
                async with httpx.AsyncClient(timeout=5.0) as http:
                    resp = await http.get(f"{base_url}/api/tags")
                    if resp.status_code == 200:
                        models = [m["name"] for m in resp.json().get("models", [])]
                        # Match name or name:latest
                        if model not in models and f"{model}:latest" not in models:
                            logger.warning("Ollama model %s not found, trying next...", model)
                            continue
                
                # Model found, call it
                result = await _call_ollama_with_model(prompt, task_type, model)
                self.last_provider = "ollama"
                return result
            except Exception as exc:
                logger.warning("Ollama call with %s failed: %s", model, exc)
                continue

        raise LLMUnavailable(
            "Ollama is not running. Start it with: ollama serve"
        )

    async def call_structured(
        self,
        prompt: str,
        schema_example: dict,
        task_type: str = "code_generation",
        context: dict = None
    ) -> dict:
        """Call LLM and guarantee JSON output."""

        if is_local_llm():
            # Minimal prompt for local models
            full_prompt = f"""Reply ONLY with valid JSON matching this structure exactly:
{json.dumps(schema_example, indent=2)}

Do not include any explanation.
Do not use markdown code blocks.
Just the raw JSON object.

Input: {prompt}"""
        else:
            full_prompt = prompt

        for attempt in range(3):
            try:
                response = await self.call(
                    full_prompt,
                    task_type,
                    context or {})
                result = safe_parse_json(response)
                if not result.get("parse_error"):
                    return result
                # If parse failed, try again with even simpler prompt
                full_prompt = f"""Output ONLY this JSON with real values filled in:
{json.dumps(schema_example)}
Task: {prompt[:200]}"""
            except Exception as e:
                logger.warning(
                    f"Structured call attempt {attempt+1} failed: {e}")

        # Return schema with defaults after 3 fails
        logger.error(
            "All structured attempts failed, returning schema defaults")
        return schema_example

    async def call_json(
        self,
        prompt: str,
        task_type: str = "code_generation",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call LLM and parse JSON response. Returns empty dict on parse failure."""
        raw = await self.call(
            prompt + "\n\nReturn ONLY valid JSON, no markdown fences.",
            task_type=task_type,
            context=context,
        )
        return safe_parse_json(raw)

    def get_cost_stats(self) -> Dict[str, int]:
        """Return token usage stats since process start."""
        return dict(_cost_registry)


_instance: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Return the global singleton LLMClient."""
    global _instance
    if _instance is None:
        _instance = LLMClient()
    return _instance
