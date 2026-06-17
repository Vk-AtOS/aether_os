"""
AetherOS — India-Specific Compliance Rules
===========================================
India compliance rules extracted from compliance.py to keep it under
600 lines. Imported by ComplianceEngine.

Covers:
  - DPDP Act 2023 (Digital Personal Data Protection)
  - IT Act 2000 / SPDI Rules 2011
  - RBI Data Localisation Directive (2018 / 2021)
  - SEBI CSCRF 2024
  - CERT-In Directions 2022
"""
from __future__ import annotations

from typing import List


def rule_india_dpdp(
    ctx: object,
    violations: list,
    reasons: List[str],
    ComplianceViolation: type,
) -> None:
    """
    India Digital Personal Data Protection (DPDP) Act 2023.

    Key obligations:
    - Notice + consent for every purpose of processing.
    - Children's data: verifiable parental consent + no tracking/targeting.
    - Cross-border transfer: allowed only to countries notified by GoI
      (whitelist approach); SaaS routed via non-whitelisted cloud -> high.
    - Significant Data Fiduciary (SDF): health, financial, genomics, biometric
      data at scale -> additional obligations (DPO, DPIA, audit).
    - IT Act 2000 (s.43A) sensitivity rule: sensitive personal data in
      fintech / healthcare / insurance -> reasonable security practices mandate.
    """
    if not ctx.handles_personal_data:
        return

    # 1. Children's data: strict
    if ctx.handles_children_data:
        violations.append(
            ComplianceViolation(
                rule_id="IN_DPDP_CHILDREN_DATA",
                area="india_dpdp",
                message=(
                    "DPDP Act 2023 §9: Children's data requires verifiable "
                    "parental/guardian consent; tracking and behavioural "
                    "advertising are prohibited. Conduct age-gating review."
                ),
                severity="high",
            )
        )
        reasons.append("India DPDP §9: children's data — parental consent mandatory, no tracking.")

    # 2. Cross-border transfer under DPDP (whitelist model)
    if ctx.uses_third_country_cloud and ctx.deployment_type != "on_prem":
        violations.append(
            ComplianceViolation(
                rule_id="IN_DPDP_CROSS_BORDER_TRANSFER",
                area="india_dpdp",
                message=(
                    "DPDP Act 2023 §16: Personal data may only be transferred "
                    "to countries on GoI's approved whitelist. Verify that all "
                    "cloud regions/providers are whitelisted or implement "
                    "contractual Standard Contractual Clauses equivalent."
                ),
                severity="high",
            )
        )
        reasons.append("India DPDP §16: cross-border transfer only to GoI-whitelisted countries.")

    # 3. Significant Data Fiduciary triggers
    sdf_industries = {"healthcare", "fintech", "insurtech", "edtech", "gov"}
    sdf_hit = sdf_industries.intersection({i.lower() for i in ctx.industries})
    if sdf_hit and ctx.handles_biometric_data:
        violations.append(
            ComplianceViolation(
                rule_id="IN_DPDP_SDF_OBLIGATIONS",
                area="india_dpdp",
                message=(
                    "DPDP Act 2023 §10-11: Likely Significant Data Fiduciary "
                    "(biometric + regulated industry). Mandatory: appoint DPO, "
                    "conduct annual DPIA, independent audit, data-localisation "
                    "per sector rules."
                ),
                severity="high",
            )
        )
        reasons.append("India DPDP: Significant Data Fiduciary obligations — DPO + DPIA required.")

    # 4. IT Act s.43A — sensitive personal data in regulated industries
    if (
        ctx.data_sensitivity == "high"
        and sdf_industries.intersection({i.lower() for i in ctx.industries})
    ):
        violations.append(
            ComplianceViolation(
                rule_id="IN_ITA_43A_SPDI",
                area="india_dpdp",
                message=(
                    "IT Act 2000 §43A / SPDI Rules 2011: Sensitive Personal Data "
                    "(passwords, financial, health, biometric, sexual orientation) "
                    "requires documented security practices (ISO 27001 or IS/ISO "
                    "equivalent), privacy policy, and explicit consent."
                ),
                severity="medium",
            )
        )
        reasons.append("India IT Act §43A: SPDI rules mandate documented security practices.")


def rule_india_rbi(
    ctx: object,
    violations: list,
    reasons: List[str],
    ComplianceViolation: type,
) -> None:
    """
    RBI data localisation + SEBI cybersecurity requirements for fintech/payments.

    RBI circular (2018 + 2021): payment system data must be stored exclusively
    in India; mirroring abroad is allowed only for international transactions with
    the Indian leg stored domestically.
    """
    fintech_tags = {"fintech", "payments", "banking", "nbfc", "upi", "rbi_regulated"}
    if fintech_tags.intersection(
        {i.lower() for i in ctx.industries} | {t.lower() for t in ctx.repo_tags}
    ):
        if ctx.uses_third_country_cloud or ctx.deployment_type == "saas":
            violations.append(
                ComplianceViolation(
                    rule_id="IN_RBI_DATA_LOCALISATION",
                    area="india_rbi",
                    message=(
                        "RBI Payment System Data Localisation Directive (2018): "
                        "All payment transaction data must be stored only in India. "
                        "SaaS or third-country cloud requires architecture review; "
                        "international leg may be mirrored but Indian copy is mandatory."
                    ),
                    severity="critical",
                )
            )
            reasons.append("RBI mandate: payment data must be stored exclusively in India.")
        else:
            violations.append(
                ComplianceViolation(
                    rule_id="IN_RBI_AUDIT_TRAIL",
                    area="india_rbi",
                    message=(
                        "RBI Master Directions: maintain immutable audit trail for "
                        "all payment transactions for minimum 5 years; implement "
                        "fraud risk management system and report incidents to RBI "
                        "within 6 hours."
                    ),
                    severity="medium",
                )
            )
            reasons.append("RBI: 5-year audit trail, 6-hour fraud incident reporting obligation.")


def rule_india_sebi(
    ctx: object,
    violations: list,
    reasons: List[str],
    ComplianceViolation: type,
) -> None:
    """
    SEBI Cybersecurity and Cyber Resilience Framework (CSCRF 2024) for
    Market Infrastructure Institutions (MII) and Registered Intermediaries.
    """
    sebi_tags = {"sebi", "broker", "depository", "stock_exchange", "asset_management", "mf", "aif"}
    if sebi_tags.intersection(
        {i.lower() for i in ctx.industries} | {t.lower() for t in ctx.repo_tags}
    ):
        violations.append(
            ComplianceViolation(
                rule_id="IN_SEBI_CSCRF",
                area="india_sebi",
                message=(
                    "SEBI CSCRF 2024: Registered intermediaries must implement "
                    "NIST CSF-aligned controls, conduct annual penetration testing, "
                    "maintain SOC, report cyber incidents within 6 hours to SEBI, "
                    "and store trade/client data in India per data localisation norms."
                ),
                severity="high",
            )
        )
        reasons.append("SEBI CSCRF 2024: annual pentest, SOC, 6-hour incident report, data localisation.")


def rule_india_certIn(
    ctx: object,
    violations: list,
    reasons: List[str],
    ComplianceViolation: type,
) -> None:
    """
    CERT-In Directions 2022 — mandatory for ALL entities in India operating ICT
    infrastructure.

    Key obligations:
    - Report cybersecurity incidents to CERT-In within 6 hours.
    - Maintain ICT logs for 180 days in India.
    - Synchronise clocks with NTP servers traceable to NTP.GOV.IN.
    - VPN/cloud/virtual asset service providers must maintain subscriber data
      for 5 years.
    """
    if ctx.handles_personal_data or ctx.data_sensitivity in {"moderate", "high"}:
        violations.append(
            ComplianceViolation(
                rule_id="IN_CERTIN_2022",
                area="india_certIn",
                message=(
                    "CERT-In Directions 2022: Report all cybersecurity incidents "
                    "to CERT-In within 6 hours of detection. Maintain ICT system "
                    "logs for 180 days within India. Clock synchronisation with "
                    "NTP.GOV.IN traceable servers is mandatory. VPN/cloud providers "
                    "must retain subscriber records for 5 years."
                ),
                severity="medium",
            )
        )
        reasons.append("CERT-In 2022: 6-hour incident reporting, 180-day log retention in India.")
