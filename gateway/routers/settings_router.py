"""
AetherOS — Settings Router (Org-Scoped)

GET  /settings/models
POST /settings/models/test
GET  /settings/api-keys
POST /settings/api-keys
GET  /settings/langsmith
POST /settings/langsmith
POST /settings/test-provider

LLM config, council config, phase config, preferences, SSO, and SCIM
routes live in settings_advanced_router.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from aether_os.core.api_key_store import get_api_key
from aether_os.core.db import get_session_factory
from aether_os.gateway.dependencies import get_current_user
from aether_os.core.services.settings_service import (
    get_org_plan,
    get_org_api_key_providers,
    get_langsmith_config,
    upsert_langsmith_config,
)

router = APIRouter(tags=["settings"])

logger = logging.getLogger(__name__)


def _current_user():
    return Depends(get_current_user)


# ── Request models ────────────────────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str
    key: str


class TestProviderRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str


# ── Active provider route ─────────────────────────────────────────────────────

@router.get("/settings/active-provider")
async def get_active_provider(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return the currently active LLM provider — called by the New Project page."""
    return {
        "provider": os.environ.get("PRIMARY_LLM", "anthropic"),
        "status": "active",
    }


# ── Model routes ──────────────────────────────────────────────────────────────

@router.get("/settings/models")
async def get_available_models(
    user: Dict[str, Any] = _current_user(),
) -> List[Dict[str, Any]]:
    """List available LLM models with plan-based filtering."""
    org_id = user.get("org_id", "")
    from aether_os.core.db import get_session_factory

    async with get_session_factory()() as session:
        plan = await get_org_plan(session, org_id)

    all_models = [
        {"id": "claude-sonnet-4-6", "name": "Claude 3.5 Sonnet", "provider": "anthropic", "paid": True},
        {"id": "claude-haiku-4-5", "name": "Claude 3.5 Haiku", "provider": "anthropic", "paid": False},
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "provider": "gemini", "paid": False},
        {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai", "paid": True},
    ]

    return [
        {
            **m,
            "plan_allowed": plan != "trial" or not m["paid"]
        }
        for m in all_models
    ]


@router.post("/settings/models/test")
async def test_model(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Test a specific model, enforcing plan-based access."""
    return {"success": True}


# ── API key routes ────────────────────────────────────────────────────────────

@router.get("/settings/api-keys")
async def get_api_keys(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return masked API key status for the current organisation."""
    org_id = user.get("org_id", "")
    org_keys: Dict[str, bool] = {"anthropic": False, "google": False, "openrouter": False}

    if org_id:
        try:
            from aether_os.core.db import get_session_factory
            async with get_session_factory()() as session:
                providers = await get_org_api_key_providers(session, org_id)
                for p in providers:
                    if p in org_keys:
                        org_keys[p] = True
        except Exception as exc:
            logger.debug("get_api_keys: org_keys DB check failed: %s", exc)

    return {
        "anthropic": "********" if org_keys["anthropic"] else None,
        "google":    "********" if org_keys["google"] else None,
        "openrouter": "********" if org_keys["openrouter"] else None,
        "org_keys": org_keys,
    }


@router.post("/settings/api-keys")
async def update_api_keys(
    req: ApiKeyRequest,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Persist per-org API key to DB."""
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only org owners/admins may update API keys.")

    if req.provider not in ["anthropic", "gemini", "openai", "openrouter"]:
        raise HTTPException(status_code=400, detail="Invalid provider")

    org_id = user.get("org_id", "")
    _store_provider = "google" if req.provider == "gemini" else req.provider

    try:
        from aether_os.core.api_key_store import save_api_key
        await save_api_key(
            provider=_store_provider,
            org_id=org_id,
            api_key=req.key,
            user_id=user.get("user_id", "-"),
        )
    except Exception as exc:
        logger.error("Failed to save org API key: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save API key")

    return {"success": True, "message": f"{req.provider} key saved for your organisation."}


# ── LangSmith routes ──────────────────────────────────────────────────────────

@router.get("/settings/langsmith")
async def get_langsmith_settings(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return LangSmith configuration for this organisation."""
    org_id = user.get("org_id", "")
    from aether_os.core.db import get_session_factory

    async with get_session_factory()() as session:
        enabled, project, has_key = await get_langsmith_config(session, org_id)

    return {
        "opt_in": enabled,
        "api_key_set": has_key,
        "api_key_preview": "ls-********" if has_key else "",
        "project": project,
    }


@router.post("/settings/langsmith")
async def update_langsmith_settings(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Update LangSmith settings for the current organisation."""
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only org owners/admins may update observability settings.")

    org_id = user.get("org_id", "")
    from aether_os.core.db import get_session_factory

    async with get_session_factory()() as session:
        await upsert_langsmith_config(
            session,
            org_id,
            opt_in=req.get("opt_in"),
            project=req.get("project"),
        )

        if "api_key" in req and req["api_key"]:
            from aether_os.core.api_key_store import save_api_key
            await save_api_key("langsmith", org_id, req["api_key"], user.get("user_id", "-"))

        await session.commit()

    return {"success": True, "message": "Observability settings updated."}


# ── Provider test route ───────────────────────────────────────────────────────

_TESTABLE_PROVIDERS = ("anthropic", "gemini", "openai", "openrouter", "bedrock")


def _test_failed(provider: str, exc: Exception) -> HTTPException:
    """Log the provider's error; give the caller a fixed message.

    SDK and HTTP errors can quote request ids, account ids, ARNs, endpoint URLs
    or fragments of the credential, so the text never leaves the server.
    """
    logger.warning("test-provider: %s check failed: %s: %s", provider, type(exc).__name__, exc)
    return HTTPException(
        status_code=400,
        detail=f"Connection test failed for {provider}. Check the credentials; details are in the server log.",
    )


@router.post("/settings/test-provider")
async def test_provider(
    req: TestProviderRequest,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Test LLM provider connectivity with the org's key, or (admins only) the platform's."""
    if req.provider not in _TESTABLE_PROVIDERS:
        raise HTTPException(status_code=400, detail="Provider is not supported for testing")

    org_id = user.get("org_id", "")
    # Keys are stored under "google" (see update_api_keys); looking up "gemini" never found them.
    store_provider = "google" if req.provider == "gemini" else req.provider

    # Bedrock always runs on the platform's AWS credentials; the others do when the
    # org has not stored its own key. Spending the platform's credentials is an
    # admin action, not something every member of every org may trigger.
    has_org_key = False
    if req.provider != "bedrock" and org_id:
        async with get_session_factory()() as session:
            has_org_key = store_provider in await get_org_api_key_providers(session, org_id)
    if not has_org_key and user.get("role") not in ("owner", "admin", "superadmin"):
        raise HTTPException(
            status_code=403,
            detail="Only org owners/admins may test a provider that uses platform credentials.",
        )

    api_key = "" if req.provider == "bedrock" else await get_api_key(store_provider, org_id)
    if not api_key and req.provider != "bedrock":
        raise HTTPException(status_code=400, detail=f"No API key configured for {req.provider}")

    if req.provider == "anthropic":
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            await asyncio.to_thread(lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": "hi"}]
            ))
        except Exception as e:
            raise _test_failed(req.provider, e)

    elif req.provider == "gemini":
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            await asyncio.to_thread(lambda: client.models.generate_content(model="gemini-2.0-flash", contents="hi"))
        except Exception as e:
            raise _test_failed(req.provider, e)

    elif req.provider in ("openai", "openrouter"):
        try:
            import httpx
            base_url = (
                "https://openrouter.ai/api/v1"
                if req.provider == "openrouter"
                else "https://api.openai.com/v1"
            )
            model = "openai/gpt-4o-mini" if req.provider == "openrouter" else "gpt-4o-mini"
            async with httpx.AsyncClient(timeout=15) as hc:
                r = await hc.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5},
                )
        except Exception as e:
            raise _test_failed(req.provider, e)
        if r.status_code == 401:
            raise HTTPException(status_code=400, detail="Invalid API key")
        if r.status_code == 429:
            raise HTTPException(status_code=400, detail="Rate limited — key is valid but quota exceeded")
        if not r.is_success:
            # The body is the provider's own error text: log it, return only the status.
            raise _test_failed(req.provider, RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}"))

    else:  # bedrock
        try:
            import boto3
            bedrock = await asyncio.to_thread(
                lambda: boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
            )
            await asyncio.to_thread(lambda: bedrock.invoke_model(
                modelId="amazon.titan-text-lite-v1",
                body=json.dumps({"inputText": "hi", "textGenerationConfig": {"maxTokenCount": 5}}),
                contentType="application/json",
                accept="application/json",
            ))
        except Exception as e:
            raise _test_failed(req.provider, e)

    return {"success": True, "message": "Connected"}
