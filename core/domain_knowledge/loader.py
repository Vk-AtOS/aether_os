"""
Domain knowledge loader — maps domain name to its knowledge pack.

Usage:
    pack = load_pack("fintech")
    design_brief["domain_knowledge"] = pack.to_dict()
    prompt += pack.prompt_injection
"""
from __future__ import annotations

import importlib
import logging
from typing import Optional

from aether_os.core.domain_knowledge.base import DomainKnowledgePack

logger = logging.getLogger(__name__)

# Map of domain name → pack module name within core.domain_knowledge.packs
_DOMAIN_PACK_MAP: dict[str, str] = {
    "fintech":          "fintech",
    "healthcare":       "healthcare",
    "ecommerce":        "ecommerce",
    "erp":              "erp",
    "logistics":        "logistics",
    "saas_multitenant": "saas",
    "saas":             "saas",
    "crm":              "saas",          # CRM shares SaaS multi-tenancy patterns
    "education":        "saas",          # LMS shares SaaS subscription patterns
}

_cache: dict[str, DomainKnowledgePack] = {}


def load_pack(domain: str) -> Optional[DomainKnowledgePack]:
    """
    Load and return the knowledge pack for the given domain.
    Returns None for domains without a dedicated pack (e.g. "general").
    Results are cached after first load.
    """
    domain = domain.lower().strip()
    pack_name = _DOMAIN_PACK_MAP.get(domain)
    if not pack_name:
        logger.debug("domain_knowledge: no pack for domain=%r", domain)
        return None

    if pack_name in _cache:
        return _cache[pack_name]

    try:
        module = importlib.import_module(f"aether_os.core.domain_knowledge.packs.{pack_name}")
        pack: DomainKnowledgePack = module.PACK
        _cache[pack_name] = pack
        logger.info(
            "domain_knowledge: loaded pack %r — %d entities, %d workflows, %d compliance rules",
            pack_name, len(pack.entities), len(pack.workflows), len(pack.compliance),
        )
        return pack
    except (ImportError, AttributeError) as e:
        logger.warning("domain_knowledge: failed to load pack %r: %s", pack_name, e)
        return None


def build_prompt_prefix(domain: str) -> str:
    """Return the PROMPT_INJECTION string for a domain, or empty string."""
    pack = load_pack(domain)
    return pack.prompt_injection if pack else ""


def build_schema_hints(domain: str) -> str:
    """Return entity schema hints for P02 architecture prompt."""
    pack = load_pack(domain)
    return pack.schema_hints() if pack else ""


def build_workflow_summary(domain: str) -> str:
    """Return state machine summary for P04 backend prompt."""
    pack = load_pack(domain)
    return pack.workflow_summary() if pack else ""


def build_compliance_summary(domain: str) -> str:
    """Return compliance briefing for P06 security review prompt."""
    pack = load_pack(domain)
    return pack.compliance_summary() if pack else ""
