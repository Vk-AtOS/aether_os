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

from aether_os.core.errors import LLMCallError
from aether_os.core.llm._org_context import _current_org_id  # noqa: F401  (re-exported for back-compat)

# ── Sub-module re-exports (preserve public API for all existing import paths) ──
from aether_os.core.llm.model_registry import (   # noqa: F401
    _HEAVY_TASKS,
    _LIGHT_TASKS,
    _GEMINI_HEAVY,
    _GEMINI_LIGHT,
    _BEDROCK_HEAVY_DEFAULT,
    _BEDROCK_LIGHT_DEFAULT,
    _select_model,
    _select_gemini_model,
    _select_bedrock_model,
)
from aether_os.core.llm.token_counter import (     # noqa: F401
    _cost_registry,
    safe_parse_json,
    _write_llm_trace,
)
from aether_os.core.llm.providers import (         # noqa: F401
    _get_anthropic_client,
    _call_anthropic,
    _call_gemini,
    _call_ollama_with_model,
    _call_ollama,
    _call_bedrock,
    _call_bedrock_vision,
)

logger = logging.getLogger(__name__)

# ── Per-request org context ───────────────────────────────────────────────────
# _current_org_id is imported from ._org_context above (and re-exported).


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


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_local_llm() -> bool:
    return os.environ.get("PRIMARY_LLM", "ollama") == "ollama"


def get_prompt_style() -> str:
    return "minimal" if is_local_llm() else "full"


def is_local_provider():
    """Legacy alias for compatibility."""
    return is_local_llm()


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

        # Problem 59: per-model cost pricing (USD per 1K tokens)
        _BEDROCK_PRICING: Dict[str, Dict[str, float]] = {
            "amazon.nova-pro-v1:0":                        {"input": 0.0008, "output": 0.0032},
            "us.amazon.nova-pro-v1:0":                     {"input": 0.0008, "output": 0.0032},
            "amazon.nova-lite-v1:0":                       {"input": 0.00006, "output": 0.00024},
            "us.amazon.nova-lite-v1:0":                    {"input": 0.00006, "output": 0.00024},
            "anthropic.claude-3-5-sonnet-20241022-v2:0":   {"input": 0.003, "output": 0.015},
            "us.anthropic.claude-3-5-sonnet-20241022-v2:0": {"input": 0.003, "output": 0.015},
            "anthropic.claude-3-haiku-20240307-v1:0":      {"input": 0.00025, "output": 0.00125},
            "us.meta.llama3-3-70b-instruct-v1:0":          {"input": 0.00072, "output": 0.00072},
            # Anthropic direct
            "claude-sonnet-4-6":                           {"input": 0.003, "output": 0.015},
            "claude-haiku-4-5-20251001":                   {"input": 0.00025, "output": 0.00125},
            # Gemini
            "gemini-2.5-pro":                              {"input": 0.00125, "output": 0.005},
            "gemini-2.0-flash":                            {"input": 0.00015, "output": 0.0006},
        }

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

            # Problem 59: compute call cost and persist to pipeline_runs + org accumulator
            try:
                _pricing = _BEDROCK_PRICING.get(model or "", None)
                if not _pricing:
                    # Try matching by suffix (e.g. model names vary by region prefix)
                    for _k, _v in _BEDROCK_PRICING.items():
                        if (model or "").endswith(_k) or _k.endswith(model or ""):
                            _pricing = _v
                            break
                if _pricing:
                    _call_cost = (
                        (tokens_in / 1000.0) * _pricing["input"]
                        + (tokens_out / 1000.0) * _pricing["output"]
                    )
                else:
                    # OpenRouter: use a safe default estimate
                    _call_cost = (tokens_in + tokens_out) / 1000.0 * 0.001

                _cost_run_id = run_id or (context.get("run_id") if context else None)
                _cost_org_id = org_id or (context.get("org_id") if context else None)

                if _call_cost > 0 and (_cost_run_id or _cost_org_id):
                    async def _persist_cost(
                        _rid=_cost_run_id, _oid=_cost_org_id, _cost=_call_cost, _model=model
                    ):
                        try:
                            from aether_os.core.db import get_session_factory
                            from sqlalchemy import text as _text
                            async with get_session_factory()() as _db:
                                if _rid:
                                    await _db.execute(
                                        _text("UPDATE pipeline_runs SET cost = COALESCE(cost, 0) + :c WHERE id = :r"),
                                        {"c": _cost, "r": _rid},
                                    )
                                if _oid:
                                    import datetime as _dt
                                    _today = _dt.date.today().isoformat()
                                    _month = _today[:7]
                                    # Update org daily/monthly accumulator in org_usage table if it exists
                                    await _db.execute(
                                        _text("""
                                            INSERT INTO org_llm_usage (org_id, date, month, cost_usd, call_count)
                                            VALUES (:org, :day, :mon, :cost, 1)
                                            ON CONFLICT (org_id, date) DO UPDATE
                                            SET cost_usd = org_llm_usage.cost_usd + :cost,
                                                call_count = org_llm_usage.call_count + 1
                                        """),
                                        {"org": _oid, "day": _today, "mon": _month, "cost": _cost},
                                    )
                                await _db.commit()
                        except Exception as _ce:
                            logger.debug("Cost persistence failed (non-blocking): %s", _ce)
                    asyncio.create_task(_persist_cost())
            except Exception as _pe:
                logger.debug("Cost computation failed (non-blocking): %s", _pe)

            return raw_response
        except Exception as exc:
            error_msg = str(exc)
            parsed_ok = False
            tokens_out = 0
            # FIX H3: Ensure we have at least the provider name if model is unknown
            if not getattr(self, 'last_model', None):
                self.last_model = getattr(self, 'last_provider', 'unknown')
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
        """Call LLM ONCE and return JSON. No retries — model_router already retries.

        On any failure (parse error, validation failure, call exception) the
        schema_example is returned and the phase's deterministic fallback path
        kicks in. The previous policy of 3 attempts × the full router chain
        could make a single architecture phase take 30+ minutes.
        """

        def _validate_architecture(data: dict) -> bool:
            """Ensure minimum required fields are present for architecture tasks."""
            if task_type != "architecture":
                return True
            required = {"tech_stack", "database_schema", "api_endpoints"}
            if not required.issubset(data.keys()):
                return False
            ts = data.get("tech_stack", {})
            if not isinstance(ts, dict):
                return False
            ts_required = {"backend", "frontend", "database"}
            return ts_required.issubset(ts.keys())

        # Always include the schema example in the prompt — Nova / Llama need it.
        full_prompt = (
            f"{prompt}\n\n"
            f"Return ONLY valid JSON (no markdown fences, no commentary) matching this exact shape:\n"
            f"{json.dumps(schema_example, indent=2)}"
        )

        try:
            response = await self.call(full_prompt, task_type, context or {})
            result = safe_parse_json(response)
            if not result.get("parse_error") and _validate_architecture(result):
                return result
            logger.info(
                "Structured call returned result that did not pass validation [task=%s] — phase fallback will fire",
                task_type,
            )
        except Exception as e:
            logger.warning("Structured call failed [task=%s]: %s", task_type, e)

        # On any failure return the schema example so the caller's fallback fires.
        # Caller MUST detect this case (e.g. tech_stack == ARCHITECTURE_SCHEMA["tech_stack"])
        # and build a deterministic fallback.
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
        Generate a vector embedding for the given text.

        Provider priority (Problem 55):
          1. AWS Bedrock Titan Embeddings (amazon.titan-embed-text-v2:0) — primary
          2. Ollama (nomic-embed-text at localhost:11434) — fallback
          3. Zero vector — last resort if both unavailable
        """
        _EMBEDDING_DIMS = {
            "nomic-embed-text": 768,
            "all-MiniLM-L6-v2": 384,
            "bge-large-en": 1024,
            "mxbai-embed-large": 1024,
            "amazon.titan-embed-text-v2:0": 1024,
        }
        bedrock_embed_model = os.environ.get(
            "BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0"
        )
        ollama_model = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
        dim = _EMBEDDING_DIMS.get(bedrock_embed_model, 1024)

        # ── Primary: AWS Bedrock Titan Embeddings ─────────────────────────────
        _bedrock_ok = (
            bool(os.environ.get("AWS_ACCESS_KEY_ID", "").strip())
            or os.environ.get("BEDROCK_ENABLED", "false").lower() == "true"
        )
        if _bedrock_ok:
            try:
                import boto3  # type: ignore
                import json as _json
                region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
                _bdr_kwargs: dict = {"region_name": region}
                _key_id = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
                _secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
                if _key_id and _secret:
                    _bdr_kwargs["aws_access_key_id"] = _key_id
                    _bdr_kwargs["aws_secret_access_key"] = _secret

                loop = asyncio.get_running_loop()

                def _invoke_bedrock_embed() -> List[float]:
                    _client = boto3.client("bedrock-runtime", **_bdr_kwargs)
                    _body = _json.dumps({"inputText": text[:8000]})
                    _resp = _client.invoke_model(
                        modelId=bedrock_embed_model,
                        body=_body,
                        contentType="application/json",
                        accept="application/json",
                    )
                    _result = _json.loads(_resp["body"].read())
                    return _result.get("embedding", [0.0] * dim)

                embedding = await loop.run_in_executor(None, _invoke_bedrock_embed)
                if embedding and len(embedding) > 0:
                    return embedding
            except Exception as _be:
                logger.warning("Bedrock Titan embedding failed (falling back to Ollama): %s", _be)

        # ── Fallback: Ollama ──────────────────────────────────────────────────
        ollama_dim = _EMBEDDING_DIMS.get(ollama_model, 768)
        try:
            import httpx
            from core.config.loader import get_config
            cfg = get_config()
            base_url = cfg.get("llm.ollama_base_url", "http://localhost:11434")

            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.post(
                    f"{base_url}/api/embeddings",
                    json={"model": ollama_model, "prompt": text[:8000]},
                )
                resp.raise_for_status()
                result = resp.json().get("embedding", [])
                if result:
                    return result
        except Exception as e:
            logger.warning("Ollama embedding failed: %s", e)

        logger.error("All embedding providers failed (Bedrock + Ollama). Returning zero vector.")
        return [0.0] * (dim if _bedrock_ok else ollama_dim)

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
