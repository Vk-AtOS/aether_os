"""
AetherOS — LLM Provider Adapters

Provider-specific async call functions for Anthropic, Google Gemini, Ollama,
and Amazon Bedrock (text + vision).  Each function handles its own retry /
backoff logic and updates the shared cost registry.

These functions are private to the llm package; external callers should use
LLMClient (from core.llm.client) or the model_router instead.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import List, Optional

from aether_os.core.errors import LLMCallError
from aether_os.core.llm._org_context import _current_org_id

logger = logging.getLogger(__name__)


def _get_current_org_id() -> Optional[str]:
    return _current_org_id.get()


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
    org_id = _get_current_org_id()
    if org_id:
        try:
            from core.api_key_store import _cache_get
            api_key = _cache_get(org_id, "anthropic")
        except Exception as exc:
            logger.debug("_get_anthropic_client: org key cache lookup failed for %s: %s", org_id, exc)

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


async def _call_anthropic(
    prompt: str,
    task_type: str,
    system: Optional[str] = None,
    max_tokens: int = 8192,
) -> str:
    """Call Anthropic API with retry + cost tracking."""
    from core.config.loader import get_config
    from aether_os.core.llm.model_registry import _select_model
    from aether_os.core.llm.token_counter import _cost_registry

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
    org_id = _get_current_org_id()
    if org_id:
        try:
            from core.api_key_store import _cache_get
            api_key = _cache_get(org_id, "google")
        except Exception as exc:
            logger.debug("_call_gemini: org key cache lookup failed for %s: %s", org_id, exc)
    if not api_key:
        api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured for this org or system.")

    from core.config.loader import get_config
    from aether_os.core.llm.model_registry import _select_gemini_model
    from aether_os.core.llm.token_counter import _cost_registry

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
    from core.config.loader import get_config
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
    except Exception as exc:
        logger.debug("_call_ollama_with_model: could not get active run context: %s", exc)
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
                        except Exception as exc:
                            logger.debug("_call_ollama_with_model: could not parse stream line: %s", exc)
                            continue
                        token = obj.get("response", "")
                        if token:
                            chunks.append(token)
                            try:
                                await _publish_event(run_id, {"type": "llm_chunk", "phase": phase, "text": token})
                            except Exception as exc:
                                logger.debug("_call_ollama_with_model: SSE publish failed (non-blocking): %s", exc)
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
                return result
            except Exception as exc:
                raise RuntimeError(f"Ollama call failed with {model}: {exc}") from exc


async def _call_ollama(prompt: str, task_type: str) -> str:
    """Call Ollama using the default model from env."""
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
    return await _call_ollama_with_model(prompt, task_type, model)


# ── Amazon Bedrock ────────────────────────────────────────────────────────────

async def _call_bedrock(
    prompt: str,
    task_type: str,
    system: Optional[str] = None,
    max_tokens: int = 8192,
    model_id: Optional[str] = None,
) -> str:
    """Call Claude on Amazon Bedrock via the Converse API (boto3, sync in executor)."""
    import boto3  # type: ignore
    from aether_os.core.llm.model_registry import _select_bedrock_model
    from aether_os.core.llm.token_counter import _cost_registry

    if model_id is None:
        model_id = _select_bedrock_model(task_type)
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    system_prompt = system or (
        "You are AetherOS, an expert autonomous software development system. "
        "Provide precise, production-quality responses."
    )

    logger.info("LLM call: provider=bedrock model=%s task=%s region=%s", model_id, task_type, region)

    _per_call_usage: dict = {}

    def _invoke() -> str:
        from botocore.config import Config as _BotoConfig  # type: ignore
        _bdr_kwargs: dict = {
            "region_name": region,
            "config": _BotoConfig(
                # read_timeout << model_router timeout (60s) so the boto3 thread
                # raises ReadTimeoutError and exits BEFORE asyncio wait_for fires.
                # Keeps the thread pool clear of zombie threads on slow models.
                # Nova Pro responses are typically 1-3s; 50s is generous headroom.
                read_timeout=50,
                connect_timeout=5,
                retries={"max_attempts": 0},  # model_router owns retry logic
            ),
        }
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
    retries = 1
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            # 55s guard — fires after botocore read_timeout=50s so thread has already exited
            text = await asyncio.wait_for(loop.run_in_executor(None, _invoke), timeout=55)
            # Record per-call LLM usage in DB (best-effort)
            try:
                from aether_os.core.billing import get_billing_tracker as _gbt
                from aether_os.orchestrator.events import ACTIVE_RUN_ID as _ARID, ACTIVE_PHASE as _AP, ACTIVE_ORG_ID as _AOID
                _run_id = _ARID.get("") or os.environ.get("ACTIVE_RUN_ID", "unknown")
                _phase  = _AP.get("") or os.environ.get("ACTIVE_PHASE", "unknown")

                # Fetch org_id if available
                _org_id = _AOID.get("") or os.environ.get("ACTIVE_ORG_ID", "-")

                asyncio.create_task(
                    _gbt()._async_record_llm_call(
                        org_id=_org_id,
                        project_id=_run_id,
                        phase=_phase,
                        model=f"bedrock/{model_id}",
                        input_tokens=_per_call_usage.get("input_tokens", 0),
                        output_tokens=_per_call_usage.get("output_tokens", 0),
                        cost_usd=0.0,
                    )
                )
            except Exception as exc:
                logger.debug("_call_bedrock: billing record failed (non-blocking): %s", exc)
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
    from aether_os.core.llm.model_registry import _select_bedrock_model

    model_id = _select_bedrock_model(task_type)
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    system_prompt = system or "You are a design expert analyzing web application screenshots."

    logger.info("LLM Vision call: provider=bedrock model=%s task=%s region=%s", model_id, task_type, region)

    def _invoke():
        from botocore.config import Config as _BotoConfig  # type: ignore
        _bdr_kwargs: dict = {
            "region_name": region,
            "config": _BotoConfig(read_timeout=120, connect_timeout=15, retries={"max_attempts": 0}),
        }
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
