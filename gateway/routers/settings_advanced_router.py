"""
AetherOS — Settings Advanced Router (Org-Scoped)

GET  /settings/llm-config
PUT  /settings/llm-config
GET  /settings/council-config
PUT  /settings/council-config
POST /settings/phases/{phase_name}/config
GET  /settings/phases/config
GET  /settings/preferences
PUT  /settings/preferences
GET  /settings/sso
PUT  /settings/sso
DELETE /settings/sso
GET  /settings/scim
POST /settings/scim/rotate
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user

router = APIRouter(tags=["settings"])

logger = logging.getLogger(__name__)


def _current_user():
    return Depends(get_current_user)


class PhaseConfigUpdate(BaseModel):
    enabled: bool
    priority: str


class SamlConfigRequest(BaseModel):
    idp_entity_id: str
    idp_sso_url: str
    idp_cert: str


# ── LLM config routes ─────────────────────────────────────────────────────────

@router.get("/settings/llm-config")
async def get_llm_config(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return LLM config for the current organisation."""
    org_id = user.get("org_id", "")
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import LlmConfig as _LC
    from sqlalchemy import select as _sel

    async with _gsf()() as session:
        db_cfg = (await session.execute(_sel(_LC).where(_LC.org_id == org_id))).scalar_one_or_none()

    if not db_cfg:
        return {
            "primary_llm": "anthropic",
            "anthropic_model": "claude-sonnet-4-6",
            "ollama_model": "qwen2.5-coder:3b",
            "langsmith_enabled": False,
            "bedrock_enabled": False,
        }

    return {
        "primary_llm": db_cfg.provider,
        "anthropic_model": db_cfg.heavy_model,
        "ollama_model": db_cfg.light_model,
        "openrouter_heavy_model": db_cfg.heavy_model,
        "openrouter_light_model": db_cfg.light_model,
        "prefer_paid": db_cfg.prefer_paid,
        "langsmith_enabled": db_cfg.langsmith_enabled,
        "langsmith_project": db_cfg.langsmith_project,
        "bedrock_enabled": db_cfg.bedrock_enabled,
        "bedrock_region": db_cfg.bedrock_region,
        "bedrock_model_heavy": db_cfg.bedrock_model_heavy,
        "bedrock_model_light": db_cfg.bedrock_model_light,
    }


@router.put("/settings/llm-config")
async def update_llm_config(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Update LLM config for the current organisation."""
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only org owners/admins may update LLM config.")

    org_id = user.get("org_id", "")
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import LlmConfig as _LC
    from sqlalchemy import select as _sel

    async with _gsf()() as session:
        db_cfg = (await session.execute(_sel(_LC).where(_LC.org_id == org_id))).scalar_one_or_none()
        if not db_cfg:
            db_cfg = _LC(org_id=org_id)
            session.add(db_cfg)

        if "primary_llm" in req: db_cfg.provider = req["primary_llm"]
        if "anthropic_model" in req: db_cfg.heavy_model = req["anthropic_model"]
        if "ollama_model" in req:    db_cfg.light_model = req["ollama_model"]
        if "openrouter_heavy_model" in req: db_cfg.heavy_model = req["openrouter_heavy_model"]
        if "openrouter_light_model" in req: db_cfg.light_model = req["openrouter_light_model"]
        if "bedrock_enabled" in req: db_cfg.bedrock_enabled = bool(req["bedrock_enabled"])
        if "langsmith_enabled" in req: db_cfg.langsmith_enabled = bool(req["langsmith_enabled"])

        await session.commit()

    return {"success": True, "message": "LLM config saved."}


# ── Council config routes ─────────────────────────────────────────────────────

@router.get("/settings/council-config")
async def get_council_config(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    org_id = user.get("org_id", "")
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import LlmConfig as _LC
    from sqlalchemy import select as _sel
    async with _gsf()() as session:
        db_cfg = (await session.execute(_sel(_LC).where(_LC.org_id == org_id))).scalar_one_or_none()

    return {
        "council_enabled": db_cfg.council_enabled if db_cfg else True,
        "council_strict_mode": db_cfg.council_strict_mode if db_cfg else False,
    }


@router.put("/settings/council-config")
async def update_council_config(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only org owners/admins may update council config.")

    org_id = user.get("org_id", "")
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import LlmConfig as _LC
    from sqlalchemy import select as _sel

    async with _gsf()() as session:
        db_cfg = (await session.execute(_sel(_LC).where(_LC.org_id == org_id))).scalar_one_or_none()
        if not db_cfg:
            db_cfg = _LC(org_id=org_id)
            session.add(db_cfg)

        db_cfg.council_enabled = bool(req.get("council_enabled", True))
        db_cfg.council_strict_mode = bool(req.get("council_strict_mode", False))
        await session.commit()

    return {"success": True}


# ── Phase config routes ───────────────────────────────────────────────────────

@router.post("/settings/phases/{phase_name}/config")
async def update_phase_config(
    phase_name: str,
    req: PhaseConfigUpdate,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    org_id = user["org_id"]
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import PhaseConfig as _PhCfg
    from sqlalchemy import select as _sel
    async with _gsf()() as session:
        cfg = (await session.execute(_sel(_PhCfg).where(_PhCfg.org_id == org_id, _PhCfg.phase_name == phase_name))).scalar_one_or_none()
        if cfg:
            cfg.enabled = 1 if req.enabled else 0
            cfg.priority = req.priority
        else:
            session.add(_PhCfg(org_id=org_id, phase_name=phase_name, enabled=1 if req.enabled else 0, priority=req.priority))
        await session.commit()
    return {"success": True}


@router.get("/settings/phases/config")
async def get_all_phase_configs(
    user: Dict[str, Any] = _current_user(),
) -> List[Dict[str, Any]]:
    org_id = user["org_id"]
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import PhaseConfig as _PhCfg
    from sqlalchemy import select as _sel
    async with _gsf()() as session:
        rows = (await session.execute(_sel(_PhCfg).where(_PhCfg.org_id == org_id))).scalars().all()

    return [{"phase_name": r.phase_name, "enabled": bool(r.enabled), "priority": r.priority} for r in rows]


# ── Preferences routes ────────────────────────────────────────────────────────

@router.get("/settings/preferences")
async def get_preferences(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    user_id = user.get("user_id") or user.get("sub", "")
    from aether_os.core.services.memory_service import get_memory_service
    ms = get_memory_service()
    return await ms.get_user_preferences(user_id)


@router.put("/settings/preferences")
async def update_preferences(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    user_id = user.get("user_id") or user.get("sub", "")
    from aether_os.core.services.memory_service import get_memory_service
    ms = get_memory_service()
    await ms.set_user_preferences(user_id, req)
    return await ms.get_user_preferences(user_id)


# ── SSO / SAML config routes ──────────────────────────────────────────────────

@router.get("/settings/sso")
async def get_sso_config(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    org_id = user.get("org_id", "")
    if not org_id:
        return {"enabled": False, "provider": None, "configured": False}
    try:
        from aether_os.core.db import get_session_factory as _gsf
        from aether_os.core.models import SamlConfig as _SC
        from sqlalchemy import select as _sel
        async with _gsf()() as session:
            cfg = (await session.execute(_sel(_SC).where(_SC.org_id == org_id))).scalar_one_or_none()
        if not cfg:
            return {"enabled": False, "provider": None, "configured": False}
        return {
            "enabled": True,
            "provider": "saml",
            "configured": True,
            "idp_entity_id": cfg.idp_entity_id,
            "idp_sso_url": cfg.idp_sso_url,
        }
    except Exception as exc:
        logger.warning("get_sso_config: DB query failed for org=%s — returning unconfigured default. Error: %s", org_id, exc)
        return {"enabled": False, "provider": None, "configured": False}


@router.put("/settings/sso")
async def upsert_sso_config(req: SamlConfigRequest, user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    org_id = user["org_id"]
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import SamlConfig as _SC
    from sqlalchemy import select as _sel
    async with _gsf()() as session:
        cfg = (await session.execute(_sel(_SC).where(_SC.org_id == org_id))).scalar_one_or_none()
        if cfg:
            cfg.idp_entity_id = req.idp_entity_id
            cfg.idp_sso_url = req.idp_sso_url
            cfg.idp_cert = req.idp_cert
        else:
            session.add(_SC(org_id=org_id, idp_entity_id=req.idp_entity_id, idp_sso_url=req.idp_sso_url, idp_cert=req.idp_cert))
        await session.commit()
    return {"success": True}


@router.delete("/settings/sso")
async def delete_sso_config(user: Dict[str, Any] = _current_user()) -> Dict[str, str]:
    org_id = user["org_id"]
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import SamlConfig as _SC
    from sqlalchemy import select as _sel
    async with _gsf()() as session:
        cfg = (await session.execute(_sel(_SC).where(_SC.org_id == org_id))).scalar_one_or_none()
        if cfg:
            await session.delete(cfg)
            await session.commit()
    return {"message": "SSO removed"}


# ── SCIM token management ─────────────────────────────────────────────────────

@router.get("/settings/scim")
async def get_scim_config(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    org_id = user["org_id"]
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import Organisation as _Org
    async with _gsf()() as session:
        org = await session.get(_Org, org_id)
    token = getattr(org, "scim_token", None)
    return {"configured": bool(token), "scim_base_url": "/api/scim/v2"}


@router.post("/settings/scim/rotate")
async def rotate_scim_token(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    if user.get("role") != "owner": raise HTTPException(status_code=403)
    import secrets
    new_token = secrets.token_urlsafe(32)
    org_id = user["org_id"]
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import Organisation as _Org
    async with _gsf()() as session:
        org = await session.get(_Org, org_id)
        if org:
            org.scim_token = new_token
            await session.commit()
    return {"token": new_token}
