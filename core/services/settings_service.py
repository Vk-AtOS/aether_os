"""
AetherOS — Settings Service

Business logic extracted from gateway/routers/settings_router.py.
All direct DB queries live here; the router delegates to these functions.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_org_plan(sess: AsyncSession, org_id: str) -> str:
    """Return the billing plan string for an org, defaulting to 'trial'."""
    from aether_os.core.models import Organisation

    org = await sess.get(Organisation, org_id)
    return org.plan if org else "trial"


async def get_org_api_key_providers(sess: AsyncSession, org_id: str) -> List[str]:
    """Return the list of provider names that have a stored API key for the org."""
    from aether_os.core.models import OrgApiKey

    rows = (await sess.execute(
        select(OrgApiKey.provider).where(OrgApiKey.org_id == org_id)
    )).scalars().all()
    return list(rows)


async def get_langsmith_config(
    sess: AsyncSession, org_id: str
) -> tuple[bool, str, bool]:
    """
    Return (langsmith_enabled, langsmith_project, has_key) for the org.
    """
    from aether_os.core.models import LlmConfig, OrgApiKey

    db_cfg = (await sess.execute(
        select(LlmConfig).where(LlmConfig.org_id == org_id)
    )).scalar_one_or_none()

    enabled = db_cfg.langsmith_enabled if db_cfg else False
    project = db_cfg.langsmith_project if db_cfg else "aetheros-factory"

    db_key = (await sess.execute(
        select(OrgApiKey).where(OrgApiKey.org_id == org_id, OrgApiKey.provider == "langsmith")
    )).scalar_one_or_none()

    return enabled, project, db_key is not None


async def upsert_langsmith_config(
    sess: AsyncSession,
    org_id: str,
    opt_in: Optional[bool],
    project: Optional[str],
) -> None:
    """Create or update LangSmith settings for the org. Caller must commit."""
    from aether_os.core.models import LlmConfig

    db_cfg = (await sess.execute(
        select(LlmConfig).where(LlmConfig.org_id == org_id)
    )).scalar_one_or_none()

    if not db_cfg:
        db_cfg = LlmConfig(org_id=org_id)
        sess.add(db_cfg)

    if opt_in is not None:
        db_cfg.langsmith_enabled = opt_in
    if project is not None:
        db_cfg.langsmith_project = project


async def get_llm_config(sess: AsyncSession, org_id: str) -> Optional[Any]:
    """Return the LlmConfig row for the org, or None if not configured."""
    from aether_os.core.models import LlmConfig

    return (await sess.execute(
        select(LlmConfig).where(LlmConfig.org_id == org_id)
    )).scalar_one_or_none()


async def upsert_llm_config(
    sess: AsyncSession, org_id: str, updates: Dict[str, Any]
) -> None:
    """Apply allowed field updates to LlmConfig. Caller must commit."""
    from aether_os.core.models import LlmConfig

    db_cfg = (await sess.execute(
        select(LlmConfig).where(LlmConfig.org_id == org_id)
    )).scalar_one_or_none()

    if not db_cfg:
        db_cfg = LlmConfig(org_id=org_id)
        sess.add(db_cfg)

    if "primary_llm" in updates:
        db_cfg.provider = updates["primary_llm"]
    if "anthropic_model" in updates:
        db_cfg.heavy_model = updates["anthropic_model"]
    if "ollama_model" in updates:
        db_cfg.light_model = updates["ollama_model"]
    if "openrouter_heavy_model" in updates:
        db_cfg.heavy_model = updates["openrouter_heavy_model"]
    if "openrouter_light_model" in updates:
        db_cfg.light_model = updates["openrouter_light_model"]
    if "bedrock_enabled" in updates:
        db_cfg.bedrock_enabled = bool(updates["bedrock_enabled"])
    if "langsmith_enabled" in updates:
        db_cfg.langsmith_enabled = bool(updates["langsmith_enabled"])


async def get_council_config(sess: AsyncSession, org_id: str) -> Dict[str, Any]:
    """Return council config fields for the org."""
    from aether_os.core.models import LlmConfig

    db_cfg = (await sess.execute(
        select(LlmConfig).where(LlmConfig.org_id == org_id)
    )).scalar_one_or_none()

    return {
        "council_enabled": db_cfg.council_enabled if db_cfg else True,
        "council_strict_mode": db_cfg.council_strict_mode if db_cfg else False,
    }


async def upsert_council_config(
    sess: AsyncSession, org_id: str, enabled: bool, strict_mode: bool
) -> None:
    """Create or update council config for the org. Caller must commit."""
    from aether_os.core.models import LlmConfig

    db_cfg = (await sess.execute(
        select(LlmConfig).where(LlmConfig.org_id == org_id)
    )).scalar_one_or_none()

    if not db_cfg:
        db_cfg = LlmConfig(org_id=org_id)
        sess.add(db_cfg)

    db_cfg.council_enabled = enabled
    db_cfg.council_strict_mode = strict_mode


async def upsert_phase_config(
    sess: AsyncSession, org_id: str, phase_name: str, enabled: bool, priority: str
) -> None:
    """Create or update phase config for a single phase. Caller must commit."""
    from aether_os.core.models import PhaseConfig

    cfg = (await sess.execute(
        select(PhaseConfig).where(
            PhaseConfig.org_id == org_id, PhaseConfig.phase_name == phase_name
        )
    )).scalar_one_or_none()

    if cfg:
        cfg.enabled = 1 if enabled else 0
        cfg.priority = priority
    else:
        sess.add(PhaseConfig(
            org_id=org_id,
            phase_name=phase_name,
            enabled=1 if enabled else 0,
            priority=priority,
        ))


async def get_all_phase_configs(sess: AsyncSession, org_id: str) -> List[Dict[str, Any]]:
    """Return all phase configs for the org."""
    from aether_os.core.models import PhaseConfig

    rows = (await sess.execute(
        select(PhaseConfig).where(PhaseConfig.org_id == org_id)
    )).scalars().all()

    return [
        {"phase_name": r.phase_name, "enabled": bool(r.enabled), "priority": r.priority}
        for r in rows
    ]


async def get_sso_config(sess: AsyncSession, org_id: str) -> Optional[Any]:
    """Return the SamlConfig row for the org, or None."""
    from aether_os.core.models import SamlConfig

    return (await sess.execute(
        select(SamlConfig).where(SamlConfig.org_id == org_id)
    )).scalar_one_or_none()


async def upsert_sso_config(
    sess: AsyncSession,
    org_id: str,
    idp_entity_id: str,
    idp_sso_url: str,
    idp_cert: str,
) -> None:
    """Create or update SAML SSO config. Caller must commit."""
    from aether_os.core.models import SamlConfig

    cfg = (await sess.execute(
        select(SamlConfig).where(SamlConfig.org_id == org_id)
    )).scalar_one_or_none()

    if cfg:
        cfg.idp_entity_id = idp_entity_id
        cfg.idp_sso_url = idp_sso_url
        cfg.idp_cert = idp_cert
    else:
        sess.add(SamlConfig(
            org_id=org_id,
            idp_entity_id=idp_entity_id,
            idp_sso_url=idp_sso_url,
            idp_cert=idp_cert,
        ))


async def delete_sso_config(sess: AsyncSession, org_id: str) -> None:
    """Delete SAML SSO config if it exists. Caller must commit."""
    from aether_os.core.models import SamlConfig

    cfg = (await sess.execute(
        select(SamlConfig).where(SamlConfig.org_id == org_id)
    )).scalar_one_or_none()

    if cfg:
        await sess.delete(cfg)
