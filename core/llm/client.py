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
import uuid
import asyncio
import contextvars
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from aether_os.core.errors import LLMCallError

logger = logging.getLogger(__name__)

# ── Per-request org context ───────────────────────────────────────────────────
_current_org_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    '_current_org_id', default=None
)


def set_org_context(org_id: str) -> None:
    """Call this at the start of each pipeline run to scope LLM key lookups."""
    _current_org_id.set(org_id)


async def init_org_llm_context(org_id: str) -> None:
    """Pre-warm API key cache for this org. Call at the start of each pipeline run."""
    from core.api_key_store import get_api_key
    set_org_context(org_id)
    for provider in ["anthropic", "google", "openrouter"]:
        try:
            await get_api_key(provider, org_id)  # populates cache
        except Exception as exc:
            logger.debug("init_org_llm_context: failed to pre-warm %s/%s: %s", org_id, provider, exc)

# Task type → tier routing
_HEAVY_TASKS = {"code_generation", "security_scan", "testing", "architecture", "review"}
_LIGHT_TASKS = {"requirements", "documentation", "summarize", "classify", "intake", "portal"}

# Gemini model assignments
_GEMINI_HEAVY = "gemini-2.5-pro"
_GEMINI_LIGHT  = "gemini-2.0-flash"

# Cost tracking (tokens)
_cost_registry: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}


async def _write_llm_trace(
    run_id: Optional[str],
    phase: str,
    task_type: str,
    model: str,
    prompt: str,
    raw_response: str,
    parsed_ok: bool,
    error: Optional[str],
    attempt: int,
    duration_ms: int,
    tokens_in: int,
    tokens_out: int,
) -> None:
    """Write one row to llm_traces. Non-blocking — failures are swallowed (FIX 22)."""
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import LLMTrace
        async with get_session_factory()() as db:
            trace = LLMTrace(
                id=str(uuid.uuid4()),
                run_id=run_id,
                phase=phase,
                task_type=task_type,
                model=model,
                prompt=prompt[:50000],       # cap at 50K chars
                raw_response=raw_response[:50000],
                parsed_ok=parsed_ok,
                error=error,
                attempt=attempt,
                duration_ms=duration_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            db.add(trace)
            await db.commit()
    except Exception as _trace_exc:
        import logging
        logging.getLogger(__name__).debug("LLM trace write failed (non-blocking): %s", _trace_exc)


# ── Anthropic ─────────────────────────────────────────────────────────────────

def _get_anthropic_client():
    """Lazy-import Anthropic SDK and return a client instance.

    Supports OpenRouter (or any OpenAI-compatible endpoint) via:
      ANTHROPIC_API_KEY=<openrouter-key>
      ANTHROPIC_BASE_URL=https://openrouter.ai/api

    When an org context is set (via set_org_context / init_org_llm_context),
    the org-specific key from the DB cache is preferred over the system env var.
    """
    try:
        import anthropic  # type: ignore
    except ImportError as exc:
        raise ImportError("anthropic SDK not installed. Run: pip install anthropic") from exc

    api_key = None
    org_id = _current_org_id.get()
    if org_id:
        try:
            from core.api_key_store import _cache_get
            api_key = _cache_get(org_id, "anthropic")
        except Exception:
            pass

    if not api_key:
        # Support ANTHROPIC_AUTH_TOKEN as alias (used by Claude Code's settings.local.json)
        api_key = (
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not configured for this org or system."
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
            self.last_model = model
            return text

        except Exception as exc:
            last_exc = exc
            exc_str = str(exc).lower()
            # Rate limit (429) and overloaded (529) need a much longer backoff
            is_rate_limit = (
                "rate" in exc_str or "429" in exc_str
                or "overloaded" in exc_str or "529" in exc_str
                or "too many" in exc_str
            )
            wait = (60 + delay * (2 ** attempt)) if is_rate_limit else delay * (2 ** attempt)
            logger.warning(
                "Anthropic call failed (attempt %d/%d, rate_limit=%s, retry_in=%.0fs): %s",
                attempt + 1, retries, is_rate_limit, wait, exc,
            )
            if attempt < retries - 1:
                await asyncio.sleep(wait)

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

    api_key = None
    org_id = _current_org_id.get()
    if org_id:
        try:
            from core.api_key_store import _cache_get
            api_key = _cache_get(org_id, "google")
        except Exception:
            pass
    if not api_key:
        api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured for this org or system.")

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
            self.last_model = model_name
            return text
        except Exception as exc:
            last_exc = exc
            exc_str = str(exc).lower()
            is_rate_limit = "429" in exc_str or "quota" in exc_str or "rate" in exc_str or "resource_exhausted" in exc_str
            wait = (60 + delay * (2 ** attempt)) if is_rate_limit else delay * (2 ** attempt)
            logger.warning(
                "Gemini call failed (attempt %d/%d, rate_limit=%s, retry_in=%.0fs): %s",
                attempt + 1, retries, is_rate_limit, wait, exc,
            )
            if attempt < retries - 1:
                await asyncio.sleep(wait)

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
                result = resp.json().get("response", "")
                self.last_model = model
                return result
            except Exception as exc:
                raise RuntimeError(f"Ollama call failed with {model}: {exc}") from exc


async def _call_ollama(prompt: str, task_type: str) -> str:
    """Call Ollama using the default model from env."""
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
    return await _call_ollama_with_model(prompt, task_type, model)


# ── Amazon Bedrock ────────────────────────────────────────────────────────────

# Bedrock default model IDs — Amazon Nova (first-party AWS, no Marketplace subscription).
# Nova models work with standard AWS credits/billing; no separate subscription required.
# To use Anthropic Claude on Bedrock, set BEDROCK_MODEL_HEAVY/LIGHT env vars to
# us.anthropic.claude-sonnet-4-6 after completing the AWS Marketplace subscription.
_BEDROCK_HEAVY_DEFAULT = "us.amazon.nova-pro-v1:0"
_BEDROCK_LIGHT_DEFAULT = "us.amazon.nova-lite-v1:0"


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
    """Call Claude on Amazon Bedrock via the Converse API (boto3, sync in executor)."""
    import boto3  # type: ignore

    model_id = _select_bedrock_model(task_type)
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    system_prompt = system or (
        "You are AetherOS, an expert autonomous software development system. "
        "Provide precise, production-quality responses."
    )

    logger.info("LLM call: provider=bedrock model=%s task=%s region=%s", model_id, task_type, region)

    _per_call_usage: dict = {}

    def _invoke() -> str:
        _bdr_kwargs: dict = {"region_name": region}
        _key_id = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
        _secret  = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
        if _key_id and _secret:
            _bdr_kwargs["aws_access_key_id"] = _key_id
            _bdr_kwargs["aws_secret_access_key"] = _secret
        # When no explicit keys, boto3 discovers credentials automatically:
        # EC2 instance profile, ECS task role, ~/.aws/credentials, etc.
        client = boto3.client("bedrock-runtime", **_bdr_kwargs)
        # Converse API: unified across providers, no anthropic_version header needed
        resp = client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max_tokens},
        )
        text = resp["output"]["message"]["content"][0]["text"]
        usage = resp.get("usage", {})
        _in  = usage.get("inputTokens", 0)
        _out = usage.get("outputTokens", 0)
        _cost_registry["prompt_tokens"] += _in
        _cost_registry["completion_tokens"] += _out
        _cost_registry["calls"] += 1
        _per_call_usage["input_tokens"] = _in
        _per_call_usage["output_tokens"] = _out
        logger.debug("Bedrock [%s] tokens=%d+%d", model_id, _in, _out)
        return text

    # Hard-failure keywords — raise immediately, no backoff
    _BEDROCK_HARD_ERRORS = (
        "invalidpaymentinstrument", "invalid_payment_instrument",
        "accessdeniedexception", "unauthorized", "not authorized",
        "model not found", "validationexception",
        "resourcenotfoundexception", "end of its life",
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
                raise
            logger.warning("Bedrock call failed (attempt %d/%d): %s", attempt + 1, retries, exc)
            if attempt < retries - 1:
                await asyncio.sleep(2 * (2 ** attempt))
    raise last_exc  # type: ignore


async def _call_bedrock_vision(
    prompt: str,
    image_bytes: bytes,
    task_type: str = "analysis",
    system: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """Call Claude on Amazon Bedrock with an image using the Converse API."""
    import boto3
    model_id = _select_bedrock_model(task_type)
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    system_prompt = system or "You are a design expert analyzing web application screenshots."

    logger.info("LLM Vision call: provider=bedrock model=%s task=%s region=%s", model_id, task_type, region)

    def _invoke():
        _bdr_kwargs: dict = {"region_name": region}
        _key_id = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
        _secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
        if _key_id and _secret:
            _bdr_kwargs["aws_access_key_id"] = _key_id
            _bdr_kwargs["aws_secret_access_key"] = _secret
            
        client = boto3.client("bedrock-runtime", **_bdr_kwargs)
        
        # Detect image format (simple)
        img_format = "png"
        if image_bytes.startswith(b"\xff\xd8"):
            img_format = "jpeg"
        elif image_bytes.startswith(b"\x47\x49\x46\x38"):
            img_format = "gif"
        elif image_bytes.startswith(b"\x89\x50\x4e\x47"):
            img_format = "png"
            
        resp = client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": {"format": img_format, "source": {"bytes": image_bytes}}},
                        {"text": prompt}
                    ]
                }
            ],
            inferenceConfig={"maxTokens": max_tokens},
        )
        return resp["output"]["message"]["content"][0]["text"]

    loop = asyncio.get_running_loop()
    retries = 3
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return await loop.run_in_executor(None, _invoke)
        except Exception as exc:
            last_exc = exc
            logger.warning("Bedrock vision call failed (attempt %d/%d): %s", attempt, retries, exc)
            if attempt < retries:
                # Exponential backoff: 2s, 4s, 8s...
                await asyncio.sleep(attempt * 2)

    raise LLMCallError(f"LLM call_vision failed after {retries} attempts: {last_exc}")


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
        self.last_model: Optional[str] = None

    async def call(
        self,
        prompt: str,
        task_type: str = "code_generation",
        context: Optional[Dict[str, Any]] = None,
        system: Optional[str] = None,
        max_tokens: int = 8192,
        org_id: Optional[str] = None,
        plan: Optional[str] = None,
        run_id: Optional[str] = None,
        phase: Optional[str] = None,
        attempt: int = 1,
    ) -> str:
        """
        Call the LLM via the multi-model router. (FIX 22 with tracing)
        """
        start_time = time.time()
        tokens_in = len(prompt) // 4
        raw_response = ""
        error_msg = None
        parsed_ok = True

        enforce_local = False
        # ... (org check logic)
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
                pass

        if context:
            ctx_str = json.dumps(context, indent=2)
            full_prompt = f"Context:\n{ctx_str}\n\n{prompt}"
        else:
            full_prompt = prompt

        # ── Context compression ──────────────────────────────────────────────
        if not enforce_local:
            try:
                from aether_os.core.llm.compressor import compress_context
                full_prompt, _compressed = await compress_context(full_prompt, task_type=task_type)
            except Exception:
                pass

        from aether_os.core.model_router import get_router
        try:
            raw_response, provider, model = await get_router().call(
                prompt=full_prompt,
                task_type=task_type,
                system=system,
                max_tokens=max_tokens,
                enforce_local=enforce_local,
                org_id=org_id,
                plan=plan,
            )
            self.last_provider = provider
            self.last_model = model
            tokens_out = len(raw_response) // 4
            return raw_response
        except Exception as exc:
            error_msg = str(exc)
            parsed_ok = False
            tokens_out = 0
            raise
        finally:
            duration_ms = int((time.time() - start_time) * 1000)
            _run_id = run_id or (context.get("run_id") if context else None)
            _phase = phase or (context.get("phase", task_type) if context else task_type)
            
            # Fire-and-forget trace write
            asyncio.create_task(_write_llm_trace(
                run_id=_run_id,
                phase=_phase,
                task_type=task_type,
                model=getattr(self, 'last_model', 'unknown'),
                prompt=prompt,
                raw_response=raw_response,
                parsed_ok=parsed_ok,
                error=error_msg,
                attempt=attempt,
                duration_ms=duration_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            ))

    async def call_structured(
        self,
        prompt: str,
        schema_example: dict,
        task_type: str = "code_generation",
        context: dict = None
    ) -> dict:
        """Call LLM and guarantee JSON output (FIX 20)."""

        def _validate_architecture(data: dict) -> bool:
            """Ensure minimum required fields are present for architecture tasks."""
            if task_type != "architecture":
                return True
            # Relaxed validation: check for tech_stack instead of individual fields
            # since the schema_example might be the whole ARCHITECTURE_SCHEMA.
            required = {"tech_stack", "database_schema", "api_endpoints"}
            if not required.issubset(data.keys()):
                return False
            ts = data.get("tech_stack", {})
            if not isinstance(ts, dict):
                return False
            ts_required = {"backend", "frontend", "database"}
            return ts_required.issubset(ts.keys())

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
                if not result.get("parse_error") and _validate_architecture(result):
                    return result
                
                # If parse failed or validation failed, try again with even simpler prompt
                logger.warning(f"Structured call validation failed [task={task_type} attempt={attempt+1}]")
                full_prompt = f"""Output ONLY this JSON with real values filled in:
{json.dumps(schema_example)}
Task: {prompt[:200]}"""
            except Exception as e:
                logger.warning(
                    f"Structured call attempt {attempt+1} failed: {e}")

        # Return schema with defaults after 3 fails
        logger.error(
            "All structured attempts failed or invalid, returning schema defaults")
        return schema_example

    async def call_json(
        self,
        prompt: str,
        task_type: str = "code_generation",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call LLM and parse JSON response. Raises LLMCallError after 3 failures."""
        for attempt in range(1, 4):
            try:
                raw = await self.call(
                    prompt + "\n\nReturn ONLY valid JSON, no markdown fences.",
                    task_type=task_type,
                    context=context,
                )
                result = safe_parse_json(raw)
                if not result.get("parse_error"):
                    return result
                
                logger.error("LLM call failed [task=%s attempt=%d]: JSON parse error", task_type, attempt)
            except Exception as exc:
                logger.error("LLM call failed [task=%s attempt=%d]: %s", task_type, attempt, exc)
                if attempt == 3:
                    raise LLMCallError(f"LLM call_json failed after 3 attempts: {exc}") from exc
            
            if attempt < 3:
                await asyncio.sleep(attempt * 2)

        raise LLMCallError(f"LLM call_json failed to return valid JSON after 3 attempts")

    async def call_vision(
        self,
        prompt: str,
        image_bytes: bytes,
        task_type: str = "analysis",
        system: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> str:
        """Call LLM with vision capabilities. Currently defaults to Bedrock/Claude."""
        return await _call_bedrock_vision(prompt, image_bytes, task_type, system, max_tokens)

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


def reinitialize() -> None:
    """
    Reset the LLMClient singleton so the next call to get_llm_client()
    returns a fresh instance.

    Call this after updating API keys or LLM config at runtime (e.g. from
    the PUT /settings/llm-config endpoint) to ensure the new configuration
    is picked up without restarting the server.

    Note: individual provider calls (Anthropic, Gemini, Bedrock) already
    read API keys from os.environ at call time, so hot-reloading os.environ
    alone is sufficient for key changes.  This function exists as an explicit
    contract for callers that want to guarantee a clean slate.
    """
    global _instance
    _instance = None
    logger.info("LLMClient singleton reset — next call will use current env config")


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
