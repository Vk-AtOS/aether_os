"""
Aether-One Legal / Export Compliance Guardrails

This module provides a local-first compliance layer that can be called from:

- CI/CD agent
- Orchestrator (before running high-risk operations)
- UI dashboards (to visualise compliance risk)

The engine operates purely on structured context, with no external calls.
It is NOT a substitute for legal advice, but enforces conservative defaults
for:

- Basic export / embargo checks
- Data residency flags (e.g., EU + third-country cloud)
- High-risk ML / AI use cases
- Crypto controls (weak vs strong crypto usage)

All checks are deterministic and suitable for automated gating.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from aether_os.core.policy.compliance_india import (
    rule_india_dpdp,
    rule_india_rbi,
    rule_india_sebi,
    rule_india_certIn,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ComplianceContext:
    """
    Input to the compliance engine.

    All fields are deliberately explicit and serialisable so callers can log or
    persist decisions as part of an approvals trail.
    """

    country_code: str  # ISO-3166 alpha-2, e.g. "US", "DE", "IN"
    region: str  # e.g. "EU", "US", "APAC", "MENA", "LATAM"
    deployment_type: str  # "on_prem", "saas", "hybrid"

    data_sensitivity: str  # "low", "moderate", "high"
    handles_personal_data: bool
    handles_biometric_data: bool
    handles_children_data: bool

    industries: List[str]
    high_risk_use_cases: List[str]  # e.g. ["biometric_identification", "surveillance"]

    uses_strong_crypto: bool
    uses_weak_crypto: bool

    customer_requires_data_residency: bool
    uses_third_country_cloud: bool  # e.g. EU customer + non-EU cloud

    model_providers: List[str]  # e.g. ["ollama", "local-llm", "vendor-us"]
    repo_tags: List[str]  # e.g. ["drone", "defense", "medical", "payments"]

    notes: Optional[str] = None  # free-form annotation
    # ISO country where the app's data will be stored; None = not stated by the requester.
    hosting_country: Optional[str] = None


@dataclass
class ComplianceViolation:
    """
    A single rule hit.

    severity:
        "critical" -> deny
        "high"     -> allow only with approval
        "medium"   -> allow only with approval
        "low"      -> allow but record as advisory
    """

    rule_id: str
    area: str  # "export", "data_residency", "ai_use", "crypto", etc.
    message: str
    severity: str


@dataclass
class ComplianceDecision:
    """
    Aggregated compliance outcome for a given context.
    """

    allowed: bool
    requires_approval: bool
    denied: bool
    violations: List[ComplianceViolation]
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "denied": self.denied,
            "violations": [asdict(v) for v in self.violations],
            "reasons": list(self.reasons),
        }


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------


class ComplianceEngine:
    """
    Local rule engine implementing conservative compliance guardrails.

    This is intentionally simple and explicit: all rules live in Python, so they
    can be audited and version-controlled.
    """

    # Simplified list of embargo / very high-risk export destinations
    EMBARGOED_COUNTRIES = {
        "IR",  # Iran
        "KP",  # North Korea
        "SY",  # Syria
        "CU",  # Cuba
        "RU",  # Russia (example; treat conservatively)
    }

    # High-risk AI use cases that should always require manual approval
    HIGH_RISK_AI_USE_CASES = {
        "biometric_identification",
        "mass_surveillance",
        "credit_scoring",
        "hiring_screening",
        "social_scoring",
        "autonomous_weapons",
        "border_control_screening",
    }

    # Tags / industries that may elevate risk
    DEFENSE_TAGS = {"defense", "military", "weapons", "dual_use"}
    SENSITIVE_INDUSTRIES = {"healthcare", "fintech", "insurtech", "gov", "defense"}

    def evaluate(self, ctx: ComplianceContext) -> ComplianceDecision:
        """
        Evaluate compliance for the given context.

        The strictest violation severity controls the outcome:

        - Any "critical" violation -> denied
        - Else any "high"/"medium" -> requires_approval
        - Else allowed
        """
        violations: List[ComplianceViolation] = []
        reasons: List[str] = []

        # Export / embargo
        self._rule_export_embargo(ctx, violations, reasons)

        # Data residency
        self._rule_data_residency(ctx, violations, reasons)

        # AI use cases
        self._rule_high_risk_ai(ctx, violations, reasons)

        # Crypto usage
        self._rule_crypto(ctx, violations, reasons)

        # Special handling for children / biometric data
        self._rule_sensitive_data(ctx, violations, reasons)

        # India-specific compliance (DPDP Act 2023, IT Act 2000, RBI, SEBI, CERT-In)
        # Only India: APAC is dozens of jurisdictions, and the India rules (RBI, CERT-In...) would
        # otherwise fire, and demand approval, for every build in the region.
        if (ctx.country_code or "").upper() == "IN" or (not ctx.country_code and ctx.region.upper() in {"IN", "INDIA"}):
            rule_india_dpdp(ctx, violations, reasons, ComplianceViolation)
            rule_india_rbi(ctx, violations, reasons, ComplianceViolation)
            rule_india_sebi(ctx, violations, reasons, ComplianceViolation)
            rule_india_certIn(ctx, violations, reasons, ComplianceViolation)

        # Determine final outcome
        severities = {v.severity for v in violations}
        denied = "critical" in severities
        requires_approval = not denied and bool(
            severities.intersection({"high", "medium"})
        )
        allowed = not denied

        if denied:
            reasons.append("One or more critical compliance rules were violated.")
        elif requires_approval:
            reasons.append(
                "One or more compliance rules flagged high or medium risk; manual approval required."
            )
        else:
            reasons.append("No blocking compliance issues detected for this context.")

        # Logging for audit trail (callers can also persist decision.to_dict())
        if violations:
            logger.warning(
                "Compliance evaluation %s for %s/%s: %s",
                "DENIED" if denied else "REQUIRES_APPROVAL" if requires_approval else "ALLOWED",
                ctx.country_code,
                ctx.region,
                "; ".join(v.message for v in violations),
            )
        else:
            logger.info(
                "Compliance evaluation ALLOWED for %s/%s (no violations).",
                ctx.country_code,
                ctx.region,
            )

        return ComplianceDecision(
            allowed=allowed,
            requires_approval=requires_approval,
            denied=denied,
            violations=violations,
            reasons=reasons,
        )

    # ---- Rule helpers -------------------------------------------------------------

    def _rule_export_embargo(
        self,
        ctx: ComplianceContext,
        violations: List[ComplianceViolation],
        reasons: List[str],
    ) -> None:
        """
        Basic export / embargo logic.

        Conservative strategy:
        - If target country is embargoed and deployment is not strictly on-prem,
          deny (critical).
        - For on-prem in embargoed countries, require approval for high-risk AI.
        """
        country = (ctx.country_code or "").upper()
        if country in self.EMBARGOED_COUNTRIES:
            if ctx.deployment_type != "on_prem":
                violations.append(
                    ComplianceViolation(
                        rule_id="EXPORT_EMBARGO_CLOUD",
                        area="export",
                        message=(
                            f"Deployment type '{ctx.deployment_type}' not allowed "
                            f"for embargoed country {country}."
                        ),
                        severity="critical",
                    )
                )
                reasons.append(
                    f"Embargoed jurisdiction {country} with non-on-prem deployment."
                )
            else:
                # On-premises: still high-risk, require approval if sensitive.
                if (
                    ctx.data_sensitivity == "high"
                    or ctx.handles_biometric_data
                    or ctx.handles_children_data
                ):
                    violations.append(
                        ComplianceViolation(
                            rule_id="EXPORT_EMBARGO_ONPREM_HIGH_RISK",
                            area="export",
                            message=(
                                f"High-sensitivity on-prem deployment in embargoed "
                                f"country {country} requires explicit approval."
                            ),
                            severity="high",
                        )
                    )
                    reasons.append(
                        f"On-prem in embargoed country {country} with high-risk data."
                    )

    def _rule_data_residency(
        self,
        ctx: ComplianceContext,
        violations: List[ComplianceViolation],
        reasons: List[str],
    ) -> None:
        """
        Data residency rule for regions like EU.

        If:
            - region == "EU"
            - customer_requires_data_residency
            - uses_third_country_cloud
        then:
            -> requires approval (high), not auto-deny.
        """
        if (
            ctx.region.upper() == "EU"
            and ctx.customer_requires_data_residency
            and ctx.uses_third_country_cloud
        ):
            violations.append(
                ComplianceViolation(
                    rule_id="DATA_RESIDENCY_EU_THIRD_COUNTRY",
                    area="data_residency",
                    message=(
                        "EU customer with data residency requirement using "
                        "third-country cloud; contractual and DPA review required."
                    ),
                    severity="high",
                )
            )
            reasons.append(
                "EU data residency requirement with third-country cloud provider."
            )

    def _rule_high_risk_ai(
        self,
        ctx: ComplianceContext,
        violations: List[ComplianceViolation],
        reasons: List[str],
    ) -> None:
        """
        High-risk AI / ML use cases must always require human review and approval.
        """
        risk_hits = self.HIGH_RISK_AI_USE_CASES.intersection(
            {u.lower() for u in ctx.high_risk_use_cases}
        )
        if risk_hits:
            violations.append(
                ComplianceViolation(
                    rule_id="AI_HIGH_RISK_USE_CASE",
                    area="ai_use",
                    message=(
                        "High-risk AI use cases detected: "
                        + ", ".join(sorted(risk_hits))
                        + ". Human legal/compliance review required."
                    ),
                    severity="high",
                )
            )
            reasons.append(
                "High-risk AI use cases present that require manual compliance review."
            )

        # Defense / dual-use signals
        defense_tags = self.DEFENSE_TAGS.intersection({t.lower() for t in ctx.repo_tags})
        if defense_tags:
            violations.append(
                ComplianceViolation(
                    rule_id="AI_DUAL_USE_DEFENSE",
                    area="ai_use",
                    message=(
                        "Repository tagged as defense/dual-use: "
                        + ", ".join(sorted(defense_tags))
                        + ". Export and dual-use review required."
                    ),
                    severity="high",
                )
            )
            reasons.append(
                "Defense / dual-use tags present; export controls must be reviewed."
            )

    def _rule_crypto(
        self,
        ctx: ComplianceContext,
        violations: List[ComplianceViolation],
        reasons: List[str],
    ) -> None:
        """
        Crypto-related rules.

        - Weak crypto in high-sensitivity contexts -> at least medium severity.
        - Strong crypto in embargoed countries -> require approval.
        """
        if ctx.uses_weak_crypto and ctx.data_sensitivity in {"high", "moderate"}:
            violations.append(
                ComplianceViolation(
                    rule_id="CRYPTO_WEAK_IN_SENSITIVE_CONTEXT",
                    area="crypto",
                    message=(
                        "Weak or deprecated cryptography used with "
                        f"{ctx.data_sensitivity} sensitivity data."
                    ),
                    severity="medium",
                )
            )
            reasons.append("Weak cryptography detected in sensitive context.")

        country = (ctx.country_code or "").upper()
        if ctx.uses_strong_crypto and country in self.EMBARGOED_COUNTRIES:
            violations.append(
                ComplianceViolation(
                    rule_id="CRYPTO_STRONG_IN_EMBARGOED_COUNTRY",
                    area="crypto",
                    message=(
                        "Strong cryptography deployed in embargoed country "
                        f"{country}; review export control applicability."
                    ),
                    severity="high",
                )
            )
            reasons.append(
                "Strong cryptography used in embargoed jurisdiction; export review required."
            )

    def _rule_sensitive_data(
        self,
        ctx: ComplianceContext,
        violations: List[ComplianceViolation],
        reasons: List[str],
    ) -> None:
        """
        Additional protections when handling children / biometric data.
        """
        if ctx.handles_children_data and ctx.deployment_type == "saas":
            violations.append(
                ComplianceViolation(
                    rule_id="DATA_CHILDREN_SAAS",
                    area="data_protection",
                    message=(
                        "SaaS deployment processing children's data; ensure "
                        "child-specific safeguards and consent flows are in place."
                    ),
                    severity="high",
                )
            )
            reasons.append(
                "Children's data processed via SaaS; additional legal safeguards required."
            )

        if ctx.handles_biometric_data and ctx.region.upper() in {"EU", "UK"}:
            violations.append(
                ComplianceViolation(
                    rule_id="DATA_BIOMETRIC_EU",
                    area="data_protection",
                    message=(
                        "Biometric data processed in EU/UK; treat as special "
                        "category data with additional lawful basis and DPIA."
                    ),
                    severity="high",
                )
            )
            reasons.append(
                "Biometric data in EU/UK context; must undergo DPIA and legal review."
            )

        # Sensitive industries + high sensitivity -> medium advisory
        if (
            ctx.data_sensitivity == "high"
            and self.SENSITIVE_INDUSTRIES.intersection({i.lower() for i in ctx.industries})
        ):
            violations.append(
                ComplianceViolation(
                    rule_id="DATA_SENSITIVE_INDUSTRY",
                    area="data_protection",
                    message=(
                        "High-sensitivity data in regulated industry "
                        f"({', '.join(sorted(self.SENSITIVE_INDUSTRIES.intersection({i.lower() for i in ctx.industries})))}); "
                        "confirm sector-specific obligations."
                    ),
                    severity="medium",
                )
            )
            reasons.append(
                "High-sensitivity data in regulated industry; sector-specific checks needed."
            )




# Convenience function if callers don't need direct access to the engine instance
def evaluate_compliance(ctx: ComplianceContext) -> ComplianceDecision:
    """
    Evaluate compliance for a context using the default engine.
    """
    engine = ComplianceEngine()
    return engine.evaluate(ctx)

