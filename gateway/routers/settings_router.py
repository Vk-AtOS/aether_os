"""
AetherOS — Settings Router

GET  /settings/api-keys
POST /settings/api-keys
GET  /settings/langsmith
POST /settings/langsmith
POST /settings/test-provider
GET  /settings/llm-config
PUT  /settings/llm-config
GET  /settings/models
POST /settings/models/test
GET  /settings/council-config
PUT  /settings/council-config
POST /settings/phases/{phase_name}/config
GET  /settings/phases/config
GET  /settings/preferences
PUT  /settings/preferences
GET  /settings/sso
PUT  /settings/sso
DELETE /settings/sso
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

router = APIRouter(tags=["settings"])

logger = logging.getLogger(__name__)


def _current_user():
    from aether_os.gateway.api import get_current_user
    return Depends(get_current_user)


# ── Request models ────────────────────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    provider: str
    key: str


class TestProviderRequest(BaseModel):
    provider: str


class PhaseConfigUpdate(BaseModel):
    enabled: bool
    priority: str


class SamlConfigRequest(BaseModel):
    idp_entity_id: str
    idp_sso_url: str
    idp_cert: str


# ── API Key routes ────────────────────────────────────────────────────────────

@router.get("/settings/api-keys")
async def get_api_keys(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return current API key configuration from .env, masking key values.
    Also reports which providers have org-specific keys in the DB."""
    env_path = pathlib.Path(__file__).parent.parent.parent / ".env"
    env_vars: Dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()

    def _mask(val: str) -> str:
        if not val:
            return ""
        return val[:8] + "..." if len(val) > 8 else val[:4] + "..."

    # Check which providers have org-specific keys in the DB
    org_keys: Dict[str, bool] = {"anthropic": False, "google": False, "openrouter": False}
    org_id = user.get("org_id", "")
    if org_id:
        try:
            from aether_os.core.db import get_session_factory as _gsf
            from aether_os.core.models import OrgApiKey as _OAK
            from sqlalchemy import select as _sel
            _sf = _gsf()
            async with _sf() as _sess:
                _rows = (await _sess.execute(
                    _sel(_OAK.provider).where(_OAK.org_id == org_id)
                )).scalars().all()
                for _p in _rows:
                    if _p in org_keys:
                        org_keys[_p] = True
        except Exception as _exc:
            logger.debug("get_api_keys: org_keys DB check failed (non-fatal): %s", _exc)

    return {
        "anthropic": _mask(env_vars.get("ANTHROPIC_API_KEY", "")),
        "google": _mask(env_vars.get("GOOGLE_API_KEY", "")),
        "openai": _mask(env_vars.get("OPENAI_API_KEY", "")),
        "openrouter": _mask(env_vars.get("OPENROUTER_API_KEY", "")),
        "primary_llm": env_vars.get("PRIMARY_LLM", "ollama"),
        "ollama_model": env_vars.get("OLLAMA_MODEL", "qwen2.5-coder:3b"),
        "org_keys": org_keys,
    }


@router.post("/settings/api-keys")
async def update_api_keys(
    req: ApiKeyRequest,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Update .env file with new API keys. Requires owner or admin role."""
    # SECURITY: only org owners/admins may overwrite provider API keys.
    # Any authenticated user could previously change ANTHROPIC_API_KEY for the whole server.
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organisation owners and admins may update API keys."
        )

    if req.provider not in ["anthropic", "gemini", "openai", "openrouter"]:
        raise HTTPException(status_code=400, detail="Invalid provider")

    if not req.key or len(req.key) <= 10:
        raise HTTPException(status_code=400, detail="Key too short or empty")

    env_path = pathlib.Path(__file__).parent.parent.parent / ".env"
    _provider_to_var = {
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    var_name = _provider_to_var[req.provider]

    lines = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()

    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{var_name}="):
            new_lines.append(f"{var_name}={req.key}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{var_name}={req.key}")

    env_path.write_text("\n".join(new_lines) + "\n")
    # Hot-reload: update os.environ immediately so the running process uses the new key
    # without needing a restart.
    os.environ[var_name] = req.key
    logger.info("API key updated and hot-reloaded for %s", req.provider)

    # Persist per-org key to DB so each customer has isolated keys.
    # Map "gemini" UI label → "google" store provider name.
    _store_provider = "google" if req.provider == "gemini" else req.provider
    org_id = user.get("org_id", "")
    if org_id:
        try:
            from aether_os.core.api_key_store import save_api_key as _save_api_key
            await _save_api_key(
                provider=_store_provider,
                org_id=org_id,
                api_key=req.key,
                user_id=user.get("sub", ""),
            )
            logger.info("Org API key persisted to DB for org=%s provider=%s", org_id, _store_provider)
        except Exception as _exc:
            logger.warning("Failed to persist org API key to DB (non-fatal): %s", _exc)

    return {
        "success": True,
        "provider": req.provider,
        "message": "Key saved and active immediately.",
    }


# ── LangSmith routes ──────────────────────────────────────────────────────────

@router.get("/settings/langsmith")
async def get_langsmith_settings(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return current LangSmith observability configuration."""
    env_path = pathlib.Path(__file__).parent.parent.parent / ".env"
    env_vars: Dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()

    opt_in_raw = env_vars.get("LANGSMITH_OPT_IN", os.environ.get("LANGSMITH_OPT_IN", "false"))
    api_key_raw = env_vars.get("LANGSMITH_API_KEY", os.environ.get("LANGSMITH_API_KEY", ""))
    return {
        "opt_in": opt_in_raw.lower() in ("1", "true", "yes"),
        "api_key_set": bool(api_key_raw),
        "api_key_preview": (api_key_raw[:8] + "...") if len(api_key_raw) > 8 else "",
        "project": env_vars.get("LANGCHAIN_PROJECT", os.environ.get("LANGCHAIN_PROJECT", "aetheros-factory")),
    }


@router.post("/settings/langsmith")
async def update_langsmith_settings(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Update LangSmith tracing opt-in and API key. Requires owner or admin role."""
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organisation owners and admins may update observability settings.",
        )

    env_path = pathlib.Path(__file__).parent.parent.parent / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()

    updates: Dict[str, str] = {}
    if "opt_in" in req:
        updates["LANGSMITH_OPT_IN"] = "true" if req["opt_in"] else "false"
    if "api_key" in req and req["api_key"]:
        updates["LANGSMITH_API_KEY"] = req["api_key"]
    if "project" in req and req["project"]:
        updates["LANGCHAIN_PROJECT"] = req["project"]

    for var_name, var_val in updates.items():
        found = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{var_name}="):
                new_lines.append(f"{var_name}={var_val}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{var_name}={var_val}")
        lines = new_lines

    env_path.write_text("\n".join(lines) + "\n")

    # Hot-reload env vars and re-init LangSmith immediately
    for var_name, var_val in updates.items():
        os.environ[var_name] = var_val

    try:
        from aether_os.core.telemetry.langsmith_tracer import init_langsmith
        init_langsmith()
    except Exception as _exc:
        logger.warning("LangSmith re-init after settings change: %s", _exc)

    return {"success": True, "updated": list(updates.keys())}


# ── Provider test route ───────────────────────────────────────────────────────

@router.post("/settings/test-provider")
async def test_provider(
    req: TestProviderRequest,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Test LLM provider connectivity."""
    if req.provider == "anthropic":
        try:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            client = anthropic.Anthropic(api_key=api_key)

            async def _call():
                # We use a synchronous call wrapped in a thread if the library doesn't support async easily,
                # but anthropic has AsyncAnthropic. For simplicity and to match the prompt's snippet:
                return client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "say hi"}]
                )

            # Wrap in executor if needed or use async client.
            # The prompt provided synchronous snippet, so we'll use to_thread for safety in async FastAPI.
            response = await asyncio.wait_for(
                asyncio.to_thread(_call),
                timeout=10.0
            )
            return {
                "success": True,
                "provider": "anthropic",
                "model": "claude-haiku-4-5-20251001",
                "message": "Connected"
            }
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Anthropic timeout")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Anthropic error: {str(e)[:200]}")

    elif req.provider == "gemini":
        try:
            import google.genai as genai
            api_key = os.environ.get("GOOGLE_API_KEY", "")
            client = genai.Client(api_key=api_key)

            async def _call():
                return client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents="say hi"
                )

            response = await asyncio.wait_for(
                asyncio.to_thread(_call),
                timeout=10.0
            )
            return {
                "success": True,
                "provider": "gemini",
                "model": "gemini-2.0-flash",
                "message": "Connected"
            }
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Gemini timeout")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Gemini error: {str(e)[:200]}")

    elif req.provider == "openrouter":
        try:
            from aether_os.core.llm.openrouter_client import call_openrouter
            result = await asyncio.wait_for(
                call_openrouter(
                    "say hi", task_type="classify", max_tokens=10,
                    model="minimax/minimax-m2.5:free",
                ),
                timeout=15.0,
            )
            return {"success": True, "provider": "openrouter", "message": "Connected", "response": result[:50]}
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="OpenRouter timeout — key may be valid but model is slow")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"OpenRouter error: {str(e)[:200]}")

    raise HTTPException(status_code=400, detail="Invalid provider")


# ── LLM config routes ─────────────────────────────────────────────────────────

@router.get("/settings/llm-config")
async def get_llm_config(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return current LLM configuration from env / DB."""
    env_path = pathlib.Path(__file__).parent.parent.parent / ".env"
    env_vars: Dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()
    raw_fallback = env_vars.get("OPENROUTER_FALLBACK_MODELS", "")
    fallback_list = [m.strip() for m in raw_fallback.split(",") if m.strip()] if raw_fallback else []
    # Include the live active model from the router so the UI shows what actually served last
    from aether_os.core.model_router import _active_model as _live_model
    return {
        "primary_llm": env_vars.get("PRIMARY_LLM", "anthropic"),
        "anthropic_model": env_vars.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        "ollama_model": env_vars.get("OLLAMA_MODEL", "qwen2.5-coder:3b"),
        "openrouter_heavy_model": env_vars.get("OPENROUTER_HEAVY_MODEL", "minimax/minimax-m2.5:free"),
        "openrouter_light_model": env_vars.get("OPENROUTER_LIGHT_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
        "openrouter_prefer_paid": env_vars.get("OPENROUTER_PREFER_PAID", "false").lower() == "true",
        "openrouter_fallback_models": fallback_list,
        "active_model": _live_model,  # e.g. "openrouter/deepseek/deepseek-r1:free" after first call
    }


@router.put("/settings/llm-config")
async def update_llm_config(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Update LLM configuration in .env. Requires owner or admin role."""
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only org owners/admins may update LLM config.")
    env_path = pathlib.Path(__file__).parent.parent.parent / ".env"
    allowed_keys = {
        "primary_llm":              "PRIMARY_LLM",
        "anthropic_model":          "ANTHROPIC_MODEL",
        "ollama_model":             "OLLAMA_MODEL",
        "openrouter_heavy_model":   "OPENROUTER_HEAVY_MODEL",
        "openrouter_light_model":   "OPENROUTER_LIGHT_MODEL",
        "openrouter_prefer_paid":   "OPENROUTER_PREFER_PAID",
    }
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updates: Dict[str, str] = {}
    for field, env_var in allowed_keys.items():
        if field in req:
            updates[env_var] = str(req[field]).lower() if isinstance(req[field], bool) else str(req[field])
    # fallback list comes in as a JSON array — store as comma-separated string
    if "openrouter_fallback_models" in req:
        models = req["openrouter_fallback_models"]
        if isinstance(models, list):
            updates["OPENROUTER_FALLBACK_MODELS"] = ",".join(str(m).strip() for m in models if str(m).strip())
        elif isinstance(models, str):
            updates["OPENROUTER_FALLBACK_MODELS"] = models
    new_lines, found = [], set()
    for line in lines:
        key = line.split("=")[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            found.add(key)
        else:
            new_lines.append(line)
    for k, v in updates.items():
        if k not in found:
            new_lines.append(f"{k}={v}")
    env_path.write_text("\n".join(new_lines) + "\n")
    # Apply immediately to running process — no restart needed
    for k, v in updates.items():
        os.environ[k] = v
    return {"success": True, "message": "Model config applied immediately."}


# ── Model catalogue routes ────────────────────────────────────────────────────

@router.get("/settings/models")
async def get_available_models(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return the curated OpenRouter model catalogue."""
    from aether_os.core.llm.openrouter_client import OPENROUTER_MODELS
    return {
        "openrouter": OPENROUTER_MODELS,
        "anthropic": {
            "claude-sonnet-4-6":           "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001":   "claude-haiku-4-5-20251001",
        },
        "gemini": {
            "gemini-2.5-pro":   "gemini-2.5-pro",
            "gemini-2.0-flash": "gemini-2.0-flash",
        },
    }


@router.post("/settings/models/test")
async def test_model(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Test that a specific OpenRouter model responds. Body: {model: str}"""
    model_id = (req.get("model") or "").strip()
    if not model_id:
        raise HTTPException(status_code=422, detail="model field required")
    try:
        from aether_os.core.llm.openrouter_client import call_openrouter
        text = await call_openrouter(
            prompt="Reply with exactly: OK",
            task_type="requirements",
            system="You are a test. Reply with exactly: OK",
            max_tokens=16,
            model=model_id,
        )
        return {"success": True, "model": model_id, "response": text[:80].strip()}
    except Exception as exc:
        return {"success": False, "model": model_id, "error": str(exc)[:200]}


# ── Council config routes ─────────────────────────────────────────────────────

@router.get("/settings/council-config")
async def get_council_config(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return current LLM Council configuration."""
    return {
        "council_enabled":     os.environ.get("COUNCIL_ENABLED",     "true").lower() != "false",
        "council_strict_mode": os.environ.get("COUNCIL_STRICT_MODE", "false").lower() == "true",
    }


@router.put("/settings/council-config")
async def update_council_config(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Update LLM Council configuration in .env. Requires owner or admin."""
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only org owners/admins may update council config.")
    env_path = pathlib.Path(__file__).parent.parent.parent / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updates: Dict[str, str] = {}
    if "council_enabled" in req:
        updates["COUNCIL_ENABLED"] = "true" if req["council_enabled"] else "false"
    if "council_strict_mode" in req:
        updates["COUNCIL_STRICT_MODE"] = "true" if req["council_strict_mode"] else "false"
    new_lines, found = [], set()
    for line in lines:
        key = line.split("=")[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            found.add(key)
        else:
            new_lines.append(line)
    for k, v in updates.items():
        if k not in found:
            new_lines.append(f"{k}={v}")
    env_path.write_text("\n".join(new_lines) + "\n")
    # Apply immediately to running process
    for k, v in updates.items():
        os.environ[k] = v
    return {"success": True, "council_enabled": updates.get("COUNCIL_ENABLED"), "council_strict_mode": updates.get("COUNCIL_STRICT_MODE")}


# ── Phase config routes ───────────────────────────────────────────────────────

@router.post("/settings/phases/{phase_name}/config")
async def update_phase_config(
    phase_name: str,
    req: PhaseConfigUpdate,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Upsert phase configuration in SQLite."""
    # Validation
    valid_phases = [
        "p01_intake_requirements", "p02_architecture", "p03_scaffolding",
        "p04_backend", "p05_frontend", "p06_review_security",
        "p07_testing", "p08_cicd_deployment", "p09_observability", "p10_docs_delivery",
    ]
    if phase_name not in valid_phases:
        raise HTTPException(status_code=400, detail="Invalid phase name")

    if req.priority not in ["low", "normal", "high"]:
        raise HTTPException(status_code=400, detail="Invalid priority")

    # Upsert phase config via ORM — scoped to org_id (T2-09)
    from aether_os.core.db import get_session_factory as _gsf_pc
    from aether_os.core.models import PhaseConfig as _PhCfg
    from sqlalchemy import select as _sel_pc
    _org_id_pc = user["org_id"]
    _sf_pc = _gsf_pc()
    async with _sf_pc() as _sess_pc:
        existing_cfg = (await _sess_pc.execute(
            _sel_pc(_PhCfg).where(_PhCfg.org_id == _org_id_pc, _PhCfg.phase_name == phase_name)
        )).scalar_one_or_none()
        if existing_cfg:
            existing_cfg.enabled = 1 if req.enabled else 0
            existing_cfg.priority = req.priority
            existing_cfg.updated_at = time.time()
        else:
            _sess_pc.add(_PhCfg(
                org_id=_org_id_pc,
                phase_name=phase_name,
                enabled=1 if req.enabled else 0,
                priority=req.priority,
                updated_at=time.time(),
            ))
        await _sess_pc.commit()

    return {
        "success": True,
        "phase": phase_name,
        "enabled": req.enabled,
        "priority": req.priority
    }


@router.get("/settings/phases/config")
async def get_all_phase_configs(
    user: Dict[str, Any] = _current_user(),
) -> List[Dict[str, Any]]:
    """Get all phase configurations, falling back to defaults."""
    valid_phases = [
        "p01_intake_requirements", "p02_architecture", "p03_scaffolding",
        "p04_backend", "p05_frontend", "p06_review_security",
        "p07_testing", "p08_cicd_deployment", "p09_observability", "p10_docs_delivery",
    ]

    configs = {p: {"phase_name": p, "enabled": True, "priority": "normal"} for p in valid_phases}

    # Load org-scoped overrides via ORM (T2-09)
    try:
        from aether_os.core.db import get_session_factory as _gsf_pcl
        from aether_os.core.models import PhaseConfig as _PhCfgL
        from sqlalchemy import select as _sel_pcl
        _sf_pcl = _gsf_pcl()
        async with _sf_pcl() as _sess_pcl:
            _cfg_rows = (await _sess_pcl.execute(
                _sel_pcl(_PhCfgL).where(_PhCfgL.org_id == user["org_id"])
            )).scalars().all()
            for _row in _cfg_rows:
                if _row.phase_name in configs:
                    configs[_row.phase_name]["enabled"] = bool(_row.enabled)
                    configs[_row.phase_name]["priority"] = _row.priority
    except Exception as _e_pcl:
        logger.debug("Phase configs ORM query failed: %s", _e_pcl)

    return list(configs.values())


# ── Preferences routes ────────────────────────────────────────────────────────

@router.get("/settings/preferences")
async def get_preferences(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return stored user preferences (session memory)."""
    user_id = user.get("user_id") or user.get("sub", "")
    try:
        from aether_os.core.services.memory_service import get_memory_service
        ms = get_memory_service()
        prefs = await ms.get_user_preferences(user_id)
        return prefs
    except Exception as exc:
        logger.error("get_preferences failed for user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Failed to load preferences")


@router.put("/settings/preferences")
async def update_preferences(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Merge new key/value pairs into stored user preferences."""
    user_id = user.get("user_id") or user.get("sub", "")
    # Strip blank keys and never allow password/token overwrite via this endpoint
    clean = {k: v for k, v in req.items() if k and k not in ("password", "token", "hashed_password")}
    if not clean:
        raise HTTPException(status_code=422, detail="No valid preference keys provided")
    try:
        from aether_os.core.services.memory_service import get_memory_service
        ms = get_memory_service()
        await ms.set_user_preferences(user_id, clean)
        updated = await ms.get_user_preferences(user_id)
        return updated
    except Exception as exc:
        logger.warning("update_preferences failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save preferences")


# ── SSO / SAML config routes (T6-04) ─────────────────────────────────────────

@router.get("/settings/sso")
async def get_sso_config(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    """Return the current org's SAML IdP configuration."""
    if user.get("role") not in ("owner",):
        raise HTTPException(status_code=403, detail="Only org owners can view SSO config")
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import SamlConfig
    from sqlalchemy import select
    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        cfg = (await session.execute(
            select(SamlConfig).where(SamlConfig.org_id == org_id)
        )).scalar_one_or_none()
    if not cfg:
        return {"configured": False}
    return {
        "configured": True,
        "id": cfg.id,
        "idp_entity_id": cfg.idp_entity_id,
        "idp_sso_url": cfg.idp_sso_url,
        "idp_cert_preview": cfg.idp_cert[:40] + "..." if len(cfg.idp_cert) > 40 else cfg.idp_cert,
        "created_at": cfg.created_at.isoformat() if cfg.created_at else None,
    }


@router.put("/settings/sso")
async def upsert_sso_config(
    req: SamlConfigRequest,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Create or replace the org's SAML IdP configuration."""
    if user.get("role") not in ("owner",):
        raise HTTPException(status_code=403, detail="Only org owners can configure SSO")
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import SamlConfig
    from sqlalchemy import select
    import uuid
    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        cfg = (await session.execute(
            select(SamlConfig).where(SamlConfig.org_id == org_id)
        )).scalar_one_or_none()
        if cfg:
            cfg.idp_entity_id = req.idp_entity_id
            cfg.idp_sso_url = req.idp_sso_url
            cfg.idp_cert = req.idp_cert
        else:
            cfg = SamlConfig(
                id=str(uuid.uuid4()),
                org_id=org_id,
                idp_entity_id=req.idp_entity_id,
                idp_sso_url=req.idp_sso_url,
                idp_cert=req.idp_cert,
            )
            session.add(cfg)
        await session.commit()
    return {"configured": True, "message": "SSO configuration saved"}


@router.delete("/settings/sso")
async def delete_sso_config(user: Dict[str, Any] = _current_user()) -> Dict[str, str]:
    """Remove the org's SAML IdP configuration."""
    if user.get("role") not in ("owner",):
        raise HTTPException(status_code=403, detail="Only org owners can remove SSO config")
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import SamlConfig
    from sqlalchemy import select
    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        cfg = (await session.execute(
            select(SamlConfig).where(SamlConfig.org_id == org_id)
        )).scalar_one_or_none()
        if not cfg:
            raise HTTPException(status_code=404, detail="No SSO configuration found")
        await session.delete(cfg)
        await session.commit()
    return {"message": "SSO configuration removed"}
