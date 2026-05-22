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
from typing import Any, Dict, List, Optional

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
    """Lazy-import Anthropic SDK and return a client instance.

    Supports OpenRouter (or any OpenAI-compatible endpoint) via:
      ANTHROPIC_API_KEY=<openrouter-key>
      ANTHROPIC_BASE_URL=https://openrouter.ai/api
    """
    try:
        import anthropic  # type: ignore
    except ImportError as exc:
        raise ImportError("anthropic SDK not installed. Run: pip install anthropic") from exc

    # Support ANTHROPIC_AUTH_TOKEN as alias (used by Claude Code's settings.local.json)
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set."
        )
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.AsyncAnthropic(**kwargs)


def _select_model(task_type: str) -> str:
    """Route task type to the appropriate model.

    When routing through OpenRouter the model strings are provider/model slugs
    (e.g. 'minimax/minimax-m2.5:free').  Fall back to env vars so the .env
    overrides take effect without requiring a config file.
    """
    from ..config.loader import get_config
    cfg = get_config()
    # Env-var overrides mirror Claude Code's settings.local.json naming
    if task_type in _LIGHT_TASKS:
        return (
            os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
            or cfg.get("models.haiku", "minimax/minimax-m2.5:free")
        )
    return (
        os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
        or cfg.get("models.primary", "minimax/minimax-m2.5:free")
    )


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

    # Use prompt caching for the system prompt — reduces cached token cost by 90%.
    # The system prompt is always the same per task_type, so cache hit rate is high.
    system_with_cache = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    for attempt in range(retries):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_with_cache,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = response.usage
            _cost_registry["prompt_tokens"] += usage.input_tokens
            _cost_registry["completion_tokens"] += usage.output_tokens
            _cost_registry["calls"] += 1
            # Some models (e.g. minimax via OpenRouter) return ThinkingBlocks
            # alongside TextBlocks — extract the first TextBlock only.
            text = next(
                (b.text for b in response.content if hasattr(b, "text")),
                ""
            )
            # Log prompt cache stats if available
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
            logger.debug(
                "Anthropic [%s] attempt=%d tokens=%d+%d cache_read=%d cache_write=%d",
                model, attempt + 1, usage.input_tokens, usage.output_tokens,
                cache_read, cache_create,
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
    """Call Ollama via HTTP with a specific model. Streams tokens when a run is active."""
    import httpx  # type: ignore
    from ..config.loader import get_config
    cfg = get_config()
    base_url = cfg.get("llm.ollama_base_url", "http://localhost:11434")
    timeout = cfg.get("llm.timeout_seconds", 120)

    logger.info("Using Ollama model: %s", model)
    logger.info("LLM call: provider=ollama model=%s task=%s", model, task_type)

    # Check if there's an active pipeline run to stream into
    try:
        from aether_os.orchestrator.events import ACTIVE_RUN_ID, ACTIVE_PHASE
        run_id = ACTIVE_RUN_ID.get()
        phase  = ACTIVE_PHASE.get()
    except Exception:
        run_id = None
        phase  = None

    url = f"{base_url}/api/generate"

    if run_id:
        # Streaming path — emit llm_chunk events via Redis pub/sub
        from aether_os.core.pipeline_state import publish_event as _publish_event
        payload = {"model": model, "prompt": prompt, "stream": True}
        chunks: list[str] = []
        async with httpx.AsyncClient(timeout=timeout) as http:
            try:
                async with http.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        token = obj.get("response", "")
                        if token:
                            chunks.append(token)
                            try:
                                await _publish_event(run_id, {"type": "llm_chunk", "phase": phase, "text": token})
                            except Exception:
                                pass
                        if obj.get("done"):
                            break
            except Exception as exc:
                raise RuntimeError(f"Ollama streaming call failed with {model}: {exc}") from exc
        return "".join(chunks)
    else:
        # Non-streaming path (no active run or queue)
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


# ── Amazon Bedrock ────────────────────────────────────────────────────────────

# Bedrock default model IDs — cross-region inference profiles (us.* prefix).
# These require a valid payment instrument on the AWS account (credits count).
# Enable via BEDROCK_ENABLED=true in environment.
_BEDROCK_HEAVY_DEFAULT = "us.anthropic.claude-sonnet-4-6"
_BEDROCK_LIGHT_DEFAULT = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def _select_bedrock_model(task_type: str) -> str:
    # Read at call time so env-var changes take effect without restart
    explicit = os.environ.get("BEDROCK_MODEL", "").strip()
    if explicit:
        return explicit
    heavy = os.environ.get("BEDROCK_MODEL_HEAVY", _BEDROCK_HEAVY_DEFAULT).strip()
    light = os.environ.get("BEDROCK_MODEL_LIGHT", _BEDROCK_LIGHT_DEFAULT).strip()
    return heavy if task_type in _HEAVY_TASKS else light


async def _call_bedrock(
    prompt: str,
    task_type: str,
    system: Optional[str] = None,
    max_tokens: int = 8192,
) -> str:
    """Call Claude on Amazon Bedrock using boto3 (sync wrapped in executor)."""
    import boto3  # type: ignore
    import json as _json

    model_id = _select_bedrock_model(task_type)
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    system_prompt = system or (
        "You are AetherOS, an expert autonomous software development system. "
        "Provide precise, production-quality responses."
    )

    logger.info("LLM call: provider=bedrock model=%s task=%s region=%s", model_id, task_type, region)

    body = _json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": prompt}],
    })

    _per_call_usage: dict = {}

    def _invoke() -> str:
        client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
        resp = client.invoke_model(
            modelId=model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = _json.loads(resp["body"].read())
        text = result.get("content", [{}])[0].get("text", "")
        usage = result.get("usage", {})
        _in  = usage.get("input_tokens", 0)
        _out = usage.get("output_tokens", 0)
        _cost_registry["prompt_tokens"] += _in
        _cost_registry["completion_tokens"] += _out
        _cost_registry["calls"] += 1
        _per_call_usage["input_tokens"] = _in
        _per_call_usage["output_tokens"] = _out
        logger.debug("Bedrock [%s] tokens=%d+%d", model_id, _in, _out)
        return text

    # boto3 is synchronous — run in executor to avoid blocking the event loop
    # Hard-failure keywords that should not be retried — raise immediately
    _BEDROCK_HARD_ERRORS = (
        "invalidpaymentinstrument", "invalid_payment_instrument",
        "accessdeniedexception", "unauthorized", "not authorized",
        "model not found", "validationexception",
    )

    loop = asyncio.get_running_loop()
    retries = 3
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            text = await loop.run_in_executor(None, _invoke)
            # Record per-call LLM usage in DB (best-effort)
            try:
                from aether_os.core.billing import get_billing_tracker as _gbt
                from aether_os.orchestrator.factory_pipeline import ACTIVE_RUN_ID as _ARID, ACTIVE_PHASE as _AP
                _run_id = _ARID.get("") or os.environ.get("ACTIVE_RUN_ID", "unknown")
                _phase  = _AP.get("") or os.environ.get("ACTIVE_PHASE", "unknown")
                asyncio.create_task(
                    _gbt()._async_record_llm_call(
                        project_id=_run_id,
                        phase=_phase,
                        model=f"bedrock/{model_id}",
                        input_tokens=_per_call_usage.get("input_tokens", 0),
                        output_tokens=_per_call_usage.get("output_tokens", 0),
                        cost_usd=0.0,
                    )
                )
            except Exception:
                pass
            return text
        except Exception as exc:
            last_exc = exc
            exc_lower = str(exc).lower()
            if any(p in exc_lower for p in _BEDROCK_HARD_ERRORS):
                logger.warning("Bedrock hard failure (no retry): %s", exc)
                raise  # immediate re-raise, no backoff
            logger.warning("Bedrock call failed (attempt %d/%d): %s", attempt + 1, retries, exc)
            if attempt < retries - 1:
                await asyncio.sleep(2 * (2 ** attempt))
    raise last_exc  # type: ignore


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
    except (json.JSONDecodeError, ValueError, AttributeError):
        pass
    # Find JSON block anywhere in response
    for pattern in [r'\{[^{}]*\}', r'\{.*?\}']:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except (json.JSONDecodeError, ValueError):
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
        org_id: Optional[str] = None,
        plan: Optional[str] = None,
    ) -> str:
        """
        Call the LLM via the multi-model router.

        Cost reduction pipeline applied automatically:
          1. Context compression (Haiku-powered, only when context is large)
          2. Semantic cache check (in router)
          3. Token budget enforcement (in router)
          4. Anthropic prompt caching via cache_control (in _call_anthropic)
          5. Provider fallback chain: Anthropic → Gemini → Ollama

        Chain: Anthropic claude-sonnet-4-6 → Gemini gemini-2.5-flash → Ollama qwen2.5-coder:3b
        Each model has individual timeouts and retry counts (see core/model_router.py).
        """
        enforce_local = False

        if org_id:
            try:
                from aether_os.core.db import get_session_factory
                from aether_os.core.models import Organisation
                from sqlalchemy import select
                async with get_session_factory()() as session:
                    stmt = select(Organisation).where(Organisation.id == org_id)
                    result = await session.execute(stmt)
                    org = result.scalar_one_or_none()
                    if org and getattr(org, "data_region", None) == "local-only":
                        enforce_local = True
                        context = context or {}
                        context["enforce_local"] = True
            except Exception:
                pass  # Non-fatal — continue without org check

        if context:
            ctx_str = json.dumps(context, indent=2)
            full_prompt = f"Context:\n{ctx_str}\n\n{prompt}"
        else:
            full_prompt = prompt

        # ── Context compression ──────────────────────────────────────────────
        # Only compress for heavy tasks when accumulated context is large.
        # Uses Haiku at ~1/10th the cost of Sonnet — pays for itself many times over.
        if not enforce_local:
            try:
                from aether_os.core.llm.compressor import compress_context
                full_prompt, _compressed = await compress_context(full_prompt, task_type=task_type)
            except Exception:
                pass  # Non-fatal — use uncompressed prompt

        from aether_os.core.model_router import get_router
        text, provider = await get_router().call(
            prompt=full_prompt,
            task_type=task_type,
            system=system,
            max_tokens=max_tokens,
            enforce_local=enforce_local,
            org_id=org_id,
            plan=plan,
        )
        self.last_provider = provider
        return text

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

    async def embed(self, text: str) -> List[float]:
        """
        Generate a vector embedding for the given text using Ollama.
        Returns a zero vector of the correct dimension if Ollama is unavailable.
        """
        _EMBEDDING_DIMS = {
            "nomic-embed-text": 768,
            "all-MiniLM-L6-v2": 384,
            "bge-large-en": 1024,
            "mxbai-embed-large": 1024,
        }
        model = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
        dim = _EMBEDDING_DIMS.get(model, 768)

        try:
            import httpx
            from ..config.loader import get_config
            cfg = get_config()
            base_url = cfg.get("llm.ollama_base_url", "http://localhost:11434")

            async with httpx.AsyncClient(timeout=30.0) as http:
                resp = await http.post(
                    f"{base_url}/api/embeddings",
                    json={"model": model, "prompt": text[:8000]},
                )
                resp.raise_for_status()
                return resp.json().get("embedding", [0.0] * dim)
        except Exception as e:
            logger.warning("Ollama embedding failed: %s", e)

        logger.error("All embedding providers failed. Returning zero vector.")
        return [0.0] * dim

    def get_cost_stats(self) -> Dict[str, int]:
        """Return token usage stats since process start."""
        return dict(_cost_registry)


_instance: Optional[LLMClient] = None


def get_llm_client(provider: Optional[str] = None) -> LLMClient:
    """Return the global singleton LLMClient.

    When *provider* is given the returned client pins that provider as the
    primary tier (by temporarily setting PRIMARY_LLM in the environment before
    the first call).  Pass provider=None for the default multi-tier client.
    """
    global _instance
    if provider is not None:
        # Provider-pinned client: always create a fresh instance so that the
        # caller gets a clean last_provider state without side-effects on the
        # process-level singleton.
        client = LLMClient()
        # Patch PRIMARY_LLM for this client's lifetime via a subclass hook.
        # The model_router reads PRIMARY_LLM at call time from os.environ, so we
        # temporarily override it inside the call.
        _orig_call = client.call

        async def _pinned_call(*args, **kwargs):
            _old = os.environ.get("PRIMARY_LLM")
            os.environ["PRIMARY_LLM"] = provider
            try:
                return await _orig_call(*args, **kwargs)
            finally:
                if _old is None:
                    os.environ.pop("PRIMARY_LLM", None)
                else:
                    os.environ["PRIMARY_LLM"] = _old

        client.call = _pinned_call  # type: ignore[method-assign]
        return client

    if _instance is None:
        _instance = LLMClient()
    return _instance
