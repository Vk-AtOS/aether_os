"""
LLM configuration API — provider detection, model listing, key storage.

Provides a provider-agnostic interface: the frontend sends an API key,
this module detects the provider, fetches available models, and stores the config.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from fastapi import Depends
from src.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/llm", tags=["llm"])

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DetectRequest(BaseModel):
    api_key: str
    aws_secret: str = ""
    aws_region: str = "us-east-1"


class ConfigureRequest(BaseModel):
    api_key: str
    model_id: str
    aws_secret: str = ""
    aws_region: str = "us-east-1"


class ModelInfo(BaseModel):
    id: str
    name: str
    context_length: int | None = None
    pricing: dict | None = None
    is_free: bool = False
    speed: str = "medium"
    capability: str = "code"


class ProviderResponse(BaseModel):
    provider: str
    models: list[ModelInfo]
    is_free_available: bool


# ---------------------------------------------------------------------------
# Provider detection helpers
# ---------------------------------------------------------------------------

def _detect_provider(api_key: str) -> str:
    k = api_key.strip()
    if k.startswith("sk-ant-"):         return "anthropic"
    if k.startswith("sk-or-v1-"):       return "openrouter"
    if k.startswith("gsk_"):            return "gemini"
    if k.startswith("AKIA"):            return "bedrock"
    if k.startswith("http://") or k.startswith("https://"): return "ollama"
    if k.startswith("sk-proj-") or (k.startswith("sk-") and len(k) > 40):
        return "openai"
    if len(k) > 50:                     return "openrouter"
    return "unknown"


def _fetch_openrouter_models(api_key: str) -> list[ModelInfo]:
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning("OpenRouter model fetch failed: %s", e)
        return []

    models = []
    for m in data.get("data", [])[:40]:
        pricing = m.get("pricing", {})
        prompt_price = float(pricing.get("prompt", "0") or "0")
        is_free = (":free" in m["id"] or prompt_price == 0)
        speed = "fast" if "7b" in m["id"].lower() or "8b" in m["id"].lower() else "medium"
        models.append(ModelInfo(
            id=m["id"],
            name=m.get("name", m["id"]),
            context_length=m.get("context_length"),
            pricing={"prompt": str(prompt_price), "completion": str(float(pricing.get("completion", "0") or "0"))} if not is_free else None,
            is_free=is_free,
            speed=speed,
            capability="code",
        ))
    # Sort: free first, then by name
    models.sort(key=lambda x: (not x.is_free, x.name))
    return models


def _fetch_openai_models(api_key: str) -> list[ModelInfo]:
    req = urllib.request.Request(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning("OpenAI model fetch failed: %s", e)
        return _openai_static()

    gpt_models = [m for m in data.get("data", []) if "gpt" in m["id"]]
    gpt_models.sort(key=lambda x: x["id"], reverse=True)
    result = []
    for m in gpt_models[:12]:
        mid = m["id"]
        speed = "fast" if "mini" in mid or "nano" in mid else "medium"
        pricing = _openai_price(mid)
        result.append(ModelInfo(id=mid, name=mid, is_free=False, speed=speed, capability="code", pricing=pricing))
    return result or _openai_static()


def _openai_static() -> list[ModelInfo]:
    return [
        ModelInfo(id="gpt-4o-mini",    name="GPT-4o Mini",    is_free=False, speed="fast",   capability="code", pricing={"prompt": "0.00015", "completion": "0.0006"}),
        ModelInfo(id="gpt-4o",         name="GPT-4o",         is_free=False, speed="medium", capability="code", pricing={"prompt": "0.005",   "completion": "0.015"}),
        ModelInfo(id="gpt-4-turbo",    name="GPT-4 Turbo",    is_free=False, speed="medium", capability="code", pricing={"prompt": "0.01",    "completion": "0.03"}),
    ]


def _openai_price(model_id: str) -> dict:
    prices: dict[str, dict] = {
        "gpt-4o-mini":   {"prompt": "0.00015",  "completion": "0.0006"},
        "gpt-4o":        {"prompt": "0.005",     "completion": "0.015"},
        "gpt-4-turbo":   {"prompt": "0.01",      "completion": "0.03"},
        "gpt-3.5-turbo": {"prompt": "0.0005",    "completion": "0.0015"},
    }
    return prices.get(model_id, {"prompt": "?", "completion": "?"})


def _fetch_anthropic_models() -> list[ModelInfo]:
    return [
        ModelInfo(id="claude-haiku-4-5-20251001", name="Claude Haiku 4.5",  is_free=False, speed="fast",   capability="code", pricing={"prompt": "0.00025", "completion": "0.00125"}),
        ModelInfo(id="claude-sonnet-4-6",          name="Claude Sonnet 4.6", is_free=False, speed="medium", capability="code", pricing={"prompt": "0.003",   "completion": "0.015"}),
        ModelInfo(id="claude-opus-4-7",            name="Claude Opus 4.7",   is_free=False, speed="slow",   capability="code", pricing={"prompt": "0.015",   "completion": "0.075"}),
    ]


def _fetch_gemini_models(api_key: str) -> list[ModelInfo]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning("Gemini model fetch failed: %s", e)
        return _gemini_static()

    models = []
    for m in data.get("models", []):
        mid = m.get("name", "").replace("models/", "")
        if "gemini" not in mid: continue
        models.append(ModelInfo(id=mid, name=m.get("displayName", mid), is_free=True, speed="fast", capability="code"))
    return models or _gemini_static()


def _gemini_static() -> list[ModelInfo]:
    return [
        ModelInfo(id="gemini-2.0-flash",     name="Gemini 2.0 Flash",     is_free=True,  speed="fast",   capability="code"),
        ModelInfo(id="gemini-1.5-flash",     name="Gemini 1.5 Flash",     is_free=True,  speed="fast",   capability="code"),
        ModelInfo(id="gemini-1.5-pro",       name="Gemini 1.5 Pro",       is_free=False, speed="medium", capability="code", pricing={"prompt": "0.00125", "completion": "0.005"}),
    ]


def _fetch_bedrock_models(access_key: str, secret_key: str, region: str) -> list[ModelInfo]:
    try:
        import boto3
        client = boto3.client("bedrock", aws_access_key_id=access_key,
                              aws_secret_access_key=secret_key, region_name=region)
        resp = client.list_foundation_models(byOutputModality="TEXT")
        models = []
        for m in resp.get("modelSummaries", [])[:20]:
            mid = m["modelId"]
            name = m.get("modelName", mid)
            models.append(ModelInfo(id=mid, name=name, is_free=False, speed="medium", capability="code",
                                    pricing={"prompt": "varies", "completion": "varies"}))
        return models
    except Exception as e:
        logger.warning("Bedrock model list failed: %s", e)
        return [
            ModelInfo(id="meta.llama3-70b-instruct-v1:0",  name="Meta Llama 3 70B",          is_free=False, speed="medium", capability="code",
                      pricing={"prompt": "0.00099", "completion": "0.00099"}),
            ModelInfo(id="meta.llama3-8b-instruct-v1:0",   name="Meta Llama 3 8B",           is_free=False, speed="fast",   capability="code",
                      pricing={"prompt": "0.0003", "completion": "0.0006"}),
            ModelInfo(id="mistral.mistral-large-2402-v1:0", name="Mistral Large",             is_free=False, speed="medium", capability="code",
                      pricing={"prompt": "0.008", "completion": "0.024"}),
            ModelInfo(id="mistral.mistral-7b-instruct-v0:2", name="Mistral 7B Instruct",     is_free=False, speed="fast",   capability="code",
                      pricing={"prompt": "0.00015", "completion": "0.0002"}),
            ModelInfo(id="amazon.nova-pro-v1:0",            name="Amazon Nova Pro",           is_free=False, speed="medium", capability="code",
                      pricing={"prompt": "varies", "completion": "varies"}),
            ModelInfo(id="amazon.nova-lite-v1:0",           name="Amazon Nova Lite",          is_free=False, speed="fast",   capability="code",
                      pricing={"prompt": "varies", "completion": "varies"}),
        ]


def _fetch_ollama_models(base_url: str) -> list[ModelInfo]:
    url = base_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=4) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning("Ollama model fetch failed: %s", e)
        return []
    models = []
    for m in data.get("models", []):
        name = m.get("name", "")
        models.append(ModelInfo(id=name, name=name, is_free=True, speed="slow", capability="code"))
    return models


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/detect", response_model=ProviderResponse)
async def detect_provider(req: DetectRequest) -> Any:
    """Detect LLM provider from API key and return available models."""
    provider = _detect_provider(req.api_key)

    if provider == "openrouter":
        models = _fetch_openrouter_models(req.api_key)
        if not models:
            raise HTTPException(status_code=400, detail="Invalid OpenRouter API key or network error")
        return ProviderResponse(provider="OpenRouter", models=models, is_free_available=any(m.is_free for m in models))

    if provider == "openai":
        models = _fetch_openai_models(req.api_key)
        return ProviderResponse(provider="OpenAI", models=models, is_free_available=False)

    if provider == "anthropic":
        models = _fetch_anthropic_models()
        return ProviderResponse(provider="Anthropic", models=models, is_free_available=False)

    if provider == "gemini":
        models = _fetch_gemini_models(req.api_key)
        return ProviderResponse(provider="Google Gemini", models=models, is_free_available=any(m.is_free for m in models))

    if provider == "bedrock":
        if not req.aws_secret:
            raise HTTPException(status_code=400, detail="AWS Secret Access Key required for Bedrock")
        models = _fetch_bedrock_models(req.api_key, req.aws_secret, req.aws_region)
        return ProviderResponse(provider="AWS Bedrock", models=models, is_free_available=False)

    if provider == "ollama":
        models = _fetch_ollama_models(req.api_key)
        if not models:
            raise HTTPException(status_code=400, detail="Ollama not reachable at the provided URL")
        return ProviderResponse(provider="Ollama (local)", models=models, is_free_available=True)

    raise HTTPException(status_code=400, detail="Unrecognised API key format — check and try again")


@router.post("/configure")
async def configure_llm(req: ConfigureRequest) -> dict:
    """Save LLM configuration to environment (runtime only; persists via .env write)."""
    provider = _detect_provider(req.api_key)

    # Write to .env so it survives restart
    _update_env_file(provider, req)

    # Apply to running process immediately
    if provider == "openrouter":
        os.environ["LLM_BACKEND"]       = "openrouter"
        os.environ["OPENROUTER_API_KEY"] = req.api_key
        os.environ["OPENROUTER_MODEL"]   = req.model_id
    elif provider == "openai":
        os.environ["LLM_BACKEND"]  = "openai"
        os.environ["OPENAI_API_KEY"] = req.api_key
        os.environ["OPENAI_MODEL"]   = req.model_id
    elif provider == "anthropic":
        os.environ["LLM_BACKEND"]     = "anthropic"
        os.environ["ANTHROPIC_API_KEY"] = req.api_key
        os.environ["ANTHROPIC_MODEL"]   = req.model_id
    elif provider == "gemini":
        os.environ["LLM_BACKEND"]  = "gemini"
        os.environ["GEMINI_API_KEY"] = req.api_key
        os.environ["GEMINI_MODEL"]   = req.model_id
    elif provider == "bedrock":
        os.environ["LLM_BACKEND"]          = "bedrock"
        os.environ["AWS_ACCESS_KEY_ID"]     = req.api_key
        os.environ["AWS_SECRET_ACCESS_KEY"] = req.aws_secret
        os.environ["AWS_REGION"]            = req.aws_region
        os.environ["BEDROCK_MODEL_ID"]      = req.model_id
    elif provider == "ollama":
        os.environ["LLM_BACKEND"]  = "ollama"
        os.environ["OLLAMA_URL"]     = req.api_key
        os.environ["OLLAMA_MODEL"]   = req.model_id

    provider_label = {
        "openrouter": "OpenRouter", "openai": "OpenAI", "anthropic": "Anthropic",
        "gemini": "Google Gemini", "bedrock": "AWS Bedrock", "ollama": "Ollama (local)",
    }.get(provider, provider.title())

    return {"success": True, "provider": provider_label, "model_id": req.model_id}


@router.get("/config")
async def get_llm_config() -> dict:
    """Return current LLM configuration (without exposing the full key)."""
    backend = os.environ.get("LLM_BACKEND", "fallback")

    config: dict = {"configured": False, "provider": None, "model_id": None, "api_key_hint": None}

    if backend == "openrouter" and os.environ.get("OPENROUTER_API_KEY"):
        k = os.environ["OPENROUTER_API_KEY"]
        config = {"configured": True, "provider": "OpenRouter",
                  "model_id": os.environ.get("OPENROUTER_MODEL"), "api_key_hint": k[:8] + "…"}
    elif backend == "openai" and os.environ.get("OPENAI_API_KEY"):
        k = os.environ["OPENAI_API_KEY"]
        config = {"configured": True, "provider": "OpenAI",
                  "model_id": os.environ.get("OPENAI_MODEL"), "api_key_hint": k[:8] + "…"}
    elif backend == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        k = os.environ["ANTHROPIC_API_KEY"]
        config = {"configured": True, "provider": "Anthropic",
                  "model_id": os.environ.get("ANTHROPIC_MODEL"), "api_key_hint": k[:8] + "…"}
    elif backend == "gemini" and os.environ.get("GEMINI_API_KEY"):
        k = os.environ["GEMINI_API_KEY"]
        config = {"configured": True, "provider": "Google Gemini",
                  "model_id": os.environ.get("GEMINI_MODEL"), "api_key_hint": k[:8] + "…"}
    elif backend in ("bedrock", "fallback") and os.environ.get("AWS_ACCESS_KEY_ID"):
        k = os.environ["AWS_ACCESS_KEY_ID"]
        config = {"configured": True, "provider": "AWS Bedrock",
                  "model_id": os.environ.get("BEDROCK_MODEL_ID"), "api_key_hint": k[:8] + "…"}
    elif backend == "ollama":
        config = {"configured": True, "provider": "Ollama (local)",
                  "model_id": os.environ.get("OLLAMA_MODEL"), "api_key_hint": "local"}

    return config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update_env_file(provider: str, req: ConfigureRequest) -> None:
    """Rewrite .env with the new LLM settings, preserving all other keys."""
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    env_path = os.path.normpath(env_path)

    lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()

    def _set(key: str, val: str) -> None:
        for i, line in enumerate(lines):
            if line.startswith(key + "="):
                lines[i] = f"{key}={val}\n"
                return
        lines.append(f"{key}={val}\n")

    provider_backend = {
        "openrouter": "openrouter", "openai": "openai", "anthropic": "anthropic",
        "gemini": "gemini", "bedrock": "bedrock", "ollama": "ollama",
    }.get(provider, "fallback")

    _set("LLM_BACKEND", provider_backend)

    if provider == "openrouter":
        _set("OPENROUTER_API_KEY", req.api_key)
        _set("OPENROUTER_MODEL",   req.model_id)
    elif provider == "openai":
        _set("OPENAI_API_KEY", req.api_key)
        _set("OPENAI_MODEL",   req.model_id)
    elif provider == "anthropic":
        _set("ANTHROPIC_API_KEY", req.api_key)
        _set("ANTHROPIC_MODEL",   req.model_id)
    elif provider == "gemini":
        _set("GEMINI_API_KEY", req.api_key)
        _set("GEMINI_MODEL",   req.model_id)
    elif provider == "bedrock":
        _set("AWS_ACCESS_KEY_ID",     req.api_key)
        _set("AWS_SECRET_ACCESS_KEY", req.aws_secret)
        _set("AWS_REGION",            req.aws_region)
        _set("BEDROCK_MODEL_ID",      req.model_id)
    elif provider == "ollama":
        _set("OLLAMA_URL",   req.api_key)
        _set("OLLAMA_MODEL", req.model_id)

    try:
        with open(env_path, "w") as f:
            f.writelines(lines)
    except Exception as e:
        logger.warning("Could not update .env: %s", e)
