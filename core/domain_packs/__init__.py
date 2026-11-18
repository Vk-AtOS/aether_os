"""
AetherOS Domain Packs — structured business domain knowledge.

A DomainPack tells the pipeline what it needs to know about a specific
business vertical to generate domain-correct code, constraints, and data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EntitySpec:
    name: str
    description: str
    typical_fields: list[str]  # field names that this entity typically has
    unique_fields: list[str]   # fields that must be unique (for seed constraints)
    fk_relationships: list[str]  # "field_name -> OtherEntity.id" format
    compliance_fields: list[str]  # fields required by regulation (e.g. HIPAA audit fields)
    indexes: list[str]  # fields that should be indexed for performance


@dataclass
class IntegrationSpec:
    name: str  # "stripe", "twilio", "sendgrid", "openai", etc.
    purpose: str  # "payment processing", "SMS notifications", etc.
    env_vars: list[str]  # required env vars: ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"]
    typical_methods: list[str]  # ["create_customer", "create_checkout_session", ...]


@dataclass
class DomainPack:
    domain: str  # "ecommerce", "healthcare", etc.
    display_name: str
    description: str
    typical_entities: list[EntitySpec]
    constraints: list[str]  # must-follow rules for this domain
    compliance_standards: list[str]  # ["PCI-DSS", "HIPAA", "GDPR", etc.]
    typical_integrations: list[IntegrationSpec]
    seed_patterns: dict[str, str]  # field_pattern: "email" -> "user{i}@example.com"
    architecture_notes: list[str]  # patterns/decisions this domain typically needs

    def get_entity_by_name(self, name: str) -> Optional[EntitySpec]:
        """Return the EntitySpec whose name matches (case-insensitive), or None."""
        name_lower = name.lower()
        for entity in self.typical_entities:
            if entity.name.lower() == name_lower:
                return entity
        return None

    def get_constraint_block(self) -> str:
        """Format constraints as a numbered list for LLM prompt injection."""
        if not self.constraints:
            return ""
        lines = [f"DOMAIN CONSTRAINTS for {self.display_name} (follow every rule):"]
        for i, rule in enumerate(self.constraints, start=1):
            lines.append(f"{i}. {rule}")
        return "\n".join(lines)

    def get_integration_names(self) -> list[str]:
        """Return list of integration names (e.g. ['stripe', 'sendgrid'])."""
        return [integration.name for integration in self.typical_integrations]


# ── Domain alias map ──────────────────────────────────────────────────────────

_DOMAIN_ALIASES: dict[str, str] = {
    # ecommerce
    "ecommerce": "ecommerce",
    "e-commerce": "ecommerce",
    "e_commerce": "ecommerce",
    "shop": "ecommerce",
    "store": "ecommerce",
    "retail": "ecommerce",
    "shopping": "ecommerce",
    # healthcare
    "healthcare": "healthcare",
    "health": "healthcare",
    "medical": "healthcare",
    "clinic": "healthcare",
    "hospital": "healthcare",
    "ehr": "healthcare",
    "emr": "healthcare",
    # ai_integrated
    "ai_integrated": "ai_integrated",
    "ai": "ai_integrated",
    "ai-integrated": "ai_integrated",
    "llm": "ai_integrated",
    "rag": "ai_integrated",
    "chatbot": "ai_integrated",
    "knowledge_base": "ai_integrated",
    "knowledge base": "ai_integrated",
    # traditional_erp
    "traditional_erp": "traditional_erp",
    "erp": "traditional_erp",
    "traditional-erp": "traditional_erp",
    "procurement": "traditional_erp",
    "manufacturing": "traditional_erp",
    "distribution": "traditional_erp",
    "inventory": "traditional_erp",
    # marketplace
    "marketplace": "marketplace",
    "market": "marketplace",
    "two-sided": "marketplace",
    "two_sided": "marketplace",
    # saas
    "saas": "saas",
    "b2b": "saas",
    "b2b_saas": "saas",
    "multi-tenant": "saas",
    "multitenant": "saas",
    "platform": "saas",
    # fintech
    "fintech": "fintech",
    "finance": "fintech",
    "financial": "fintech",
    "payment": "fintech",
    "payments": "fintech",
    "banking": "fintech",
    "bank": "fintech",
    "invoice": "fintech",
    "invoicing": "fintech",
    "wallet": "fintech",
    "ledger": "fintech",
    # government
    "government": "government",
    "gov": "government",
    "public_sector": "government",
    "civic": "government",
    "municipality": "government",
    # social
    "social": "social",
    "social_platform": "social",
    "social-platform": "social",
    "social_network": "social",
    "social network": "social",
    "social media": "social",
    "community": "social",
    "forum": "social",
    "blog": "social",
    # iot
    "iot": "iot",
    "iot_dashboard": "iot",
    "iot-dashboard": "iot",
    "internet_of_things": "iot",
    "internet of things": "iot",
    "sensor": "iot",
    "telemetry": "iot",
    "scada": "iot",
    "smart_home": "iot",
}


def _load_pack(canonical: str) -> Optional[DomainPack]:
    """Lazy-load the module for a canonical domain key and return its pack."""
    try:
        if canonical == "ecommerce":
            from aether_os.core.domain_packs.ecommerce_pack import ECOMMERCE_PACK
            return ECOMMERCE_PACK
        if canonical == "healthcare":
            from aether_os.core.domain_packs.healthcare_pack import HEALTHCARE_PACK
            return HEALTHCARE_PACK
        if canonical == "ai_integrated":
            from aether_os.core.domain_packs.ai_integrated_pack import AI_INTEGRATED_PACK
            return AI_INTEGRATED_PACK
        if canonical == "traditional_erp":
            from aether_os.core.domain_packs.erp_pack import ERP_PACK
            return ERP_PACK
        if canonical == "marketplace":
            from aether_os.core.domain_packs.marketplace_pack import MARKETPLACE_PACK
            return MARKETPLACE_PACK
        if canonical == "saas":
            from aether_os.core.domain_packs.saas_pack import SAAS_PACK
            return SAAS_PACK
        if canonical == "fintech":
            from aether_os.core.domain_packs.fintech_pack import FINTECH_PACK
            return FINTECH_PACK
        if canonical == "erp":
            from aether_os.core.domain_packs.erp_pack import ERP_PACK
            return ERP_PACK
        if canonical == "government":
            from aether_os.core.domain_packs.government_pack import GOVERNMENT_PACK
            return GOVERNMENT_PACK
        if canonical == "social":
            from aether_os.core.domain_packs.social_pack import SOCIAL_PACK
            return SOCIAL_PACK
        if canonical == "iot":
            from aether_os.core.domain_packs.iot_pack import IOT_PACK
            return IOT_PACK
    except Exception as e:
        logger.warning("Failed to load domain pack for '%s': %s", canonical, e)
    return None


def get_domain_pack(domain: str) -> Optional[DomainPack]:
    """Return the appropriate domain pack for a given domain string.

    Returns None if no pack matches the given domain string.

    Normalization:
    - Strips whitespace, lowercases
    - Resolves aliases: "e-commerce" -> "ecommerce", "health" -> "healthcare", etc.
    """
    if not domain:
        return None
    normalized = domain.lower().strip()
    canonical = _DOMAIN_ALIASES.get(normalized)
    if canonical is None:
        logger.warning("No domain pack alias found for '%s'", domain)
        return None
    return _load_pack(canonical)


__all__ = [
    "EntitySpec",
    "IntegrationSpec",
    "DomainPack",
    "get_domain_pack",
]
