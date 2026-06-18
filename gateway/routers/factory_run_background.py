"""
AetherOS — Factory Run Background Helpers
Extracted from factory_ops_router.py.

Contains the background task logic for running a pipeline:
  - run_pipeline_background(): runs council pre-flight + factory + post-build hooks
  - build_spec_preamble(): constructs the designer_spec preamble string
  - run_compliance_precheck(): validates production_country before pipeline start
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# ── Embargoed countries — cannot be a production target ──────────────────────
_EMBARGOED = {"CU", "IR", "KP", "SY", "RU", "BY"}

_REGION_MAP = {
    "AT": "EU", "BE": "EU", "CZ": "EU", "DE": "EU", "DK": "EU", "ES": "EU",
    "FI": "EU", "FR": "EU", "GR": "EU", "HR": "EU", "HU": "EU", "IE": "EU",
    "IT": "EU", "NL": "EU", "PL": "EU", "PT": "EU", "RO": "EU", "SE": "EU",
    "SK": "EU", "CH": "EU", "NO": "EU", "GB": "UK",
    "US": "US", "CA": "CANADA",
    "BR": "LATAM", "MX": "LATAM", "AR": "LATAM", "CL": "LATAM", "CO": "LATAM",
    "AU": "APAC", "NZ": "APAC", "IN": "APAC", "SG": "APAC", "JP": "APAC",
    "KR": "APAC", "TH": "APAC", "PH": "APAC", "ID": "APAC", "MY": "APAC",
    "VN": "APAC", "HK": "APAC", "TW": "APAC",
    "AE": "MENA", "SA": "MENA", "IL": "MENA", "EG": "MENA",
    "NG": "AFRICA", "ZA": "AFRICA",
    "CN": "CHINA",
}


def build_spec_preamble(
    designer_spec: Dict[str, Any],
    existing_schema: Optional[Dict[str, Any]],
) -> str:
    """Return a structured spec preamble string to prepend to raw_input."""
    fe = designer_spec.get("frontend", {})
    be = designer_spec.get("backend", {})
    inf = designer_spec.get("infra", {})
    ft = designer_spec.get("features", {})
    ds = designer_spec.get("design", {})
    preamble = (
        "=== PROJECT SPECIFICATION ===\n"
        "Tech Stack:\n"
        f"  Frontend: {fe.get('framework','')} + {fe.get('styling','')}\n"
        f"  State: {fe.get('state_management','')}\n"
        f"  Forms: {fe.get('form_library','')}\n"
        f"  Data Fetching: {fe.get('data_fetching','')}\n"
        f"  Backend: {be.get('framework','')} + {be.get('database','')} + {be.get('orm','')}\n"
        f"  Auth: {be.get('auth','')}\n"
        f"  API: {be.get('api_style','')}\n"
        f"  Infrastructure: {inf.get('deployment','')}, cache={inf.get('cache','')}, queue={inf.get('queue','')}\n"
        f"  File Storage: {inf.get('file_storage','')}, Email: {inf.get('email','')}\n"
        f"  Features: multi_tenant={ft.get('multi_tenancy',False)}, audit_log={ft.get('audit_log',False)}, "
        f"rate_limiting={ft.get('rate_limiting',True)}, webhooks={ft.get('webhooks_out',False)}, "
        f"realtime={ft.get('realtime','None')}, payments={ft.get('payments','None')}, "
        f"i18n={ft.get('internationalization',False)}\n"
        "\nDesign Tokens:\n"
        f"  Primary color: {ds.get('primary_hex','#6366f1')}\n"
        f"  Secondary color: {ds.get('secondary_hex','#8b5cf6')}\n"
        f"  Background: {ds.get('background_hex','#0f172a')}\n"
        f"  Surface: {ds.get('surface_hex','#1e293b')}\n"
        f"  Font pairing: {ds.get('font_pairing','Inter + Inter')}\n"
        f"  Border radius: {ds.get('border_radius','Rounded (8px)')}\n"
        f"  Layout: {ds.get('layout','sidebar-topbar')}\n"
        f"  Component density: {ds.get('density','Normal')}\n"
        f"  UI Theme: {ds.get('ui_theme','default')}\n"
        "\n=== PROJECT REQUIREMENT ===\n"
    )
    if existing_schema and isinstance(existing_schema, dict):
        tables = existing_schema.get("tables", [])
        if tables:
            schema_lines = ["", "=== EXISTING DATABASE SCHEMA (use this, do not invent tables) ==="]
            for t in tables[:20]:
                cols = ", ".join(
                    c.get("name", c) if isinstance(c, dict) else c
                    for c in t.get("columns", [])[:10]
                )
                schema_lines.append(f"  Table: {t.get('name', '?')} — columns: {cols}")
            preamble += "\n".join(schema_lines) + "\n"
    return preamble


def run_compliance_precheck(
    production_country: str,
    compliance_flags: Dict[str, Any],
    domain: str,
    designer_spec: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate production_country against embargoed list and run ComplianceEngine.
    Returns updated designer_spec dict (with compliance_context injected).
    Raises HTTPException on hard blocks.
    """
    if production_country in _EMBARGOED:
        raise HTTPException(
            status_code=403,
            detail=f"Production in '{production_country}' is blocked — embargoed jurisdiction."
        )

    try:
        from aether_os.core.policy.compliance import ComplianceEngine, ComplianceContext
        _region = _REGION_MAP.get(production_country, "global")
        _ctx = ComplianceContext(
            country_code=production_country,
            region=_region,
            deployment_type=compliance_flags.get("deployment_type", "saas"),
            data_sensitivity=compliance_flags.get("data_sensitivity", "moderate"),
            handles_personal_data=compliance_flags.get("handles_personal_data", True),
            handles_biometric_data=compliance_flags.get("handles_biometric_data", False),
            handles_children_data=compliance_flags.get("handles_children_data", False),
            industries=[domain] if domain else [],
            high_risk_use_cases=[],
            uses_strong_crypto=True,
            uses_weak_crypto=False,
            customer_requires_data_residency=compliance_flags.get("requires_data_residency", False),
            uses_third_country_cloud=False,
            model_providers=[],
            repo_tags=[],
        )
        _decision = ComplianceEngine().evaluate(_ctx)
        if _decision.denied:
            raise HTTPException(
                status_code=403,
                detail=f"Compliance check denied: {'; '.join(_decision.reasons)}"
            )
        if not isinstance(designer_spec, dict):
            designer_spec = {}
        designer_spec["compliance_context"] = {
            "country_code": production_country,
            "region": _region,
            "allowed": _decision.allowed,
            "requires_approval": _decision.requires_approval,
            "violations": [
                {"rule_id": v.rule_id, "severity": v.severity, "message": v.message}
                for v in _decision.violations
            ],
            **compliance_flags,
        }
        logger.info(
            "Compliance pre-check: country=%s region=%s allowed=%s requires_approval=%s violations=%d",
            production_country, _region, _decision.allowed,
            _decision.requires_approval, len(_decision.violations),
        )
    except HTTPException:
        raise
    except Exception as _comp_exc:
        logger.warning("Compliance pre-check non-fatal error: %s", _comp_exc)

    return designer_spec


async def run_pipeline_background(
    *,
    factory: Any,
    run_id: str,
    client_id: str,
    raw_input: str,
    domain: str,
    project_name: Optional[str],
    org_id: str,
    user_id: Optional[str],
    github_url: Optional[str],
    designer_spec: Dict[str, Any],
    tech_preferences: Dict[str, Any],
    model_preference: str,
    priority: str,
    codebase_mode: str,
    existing_schema: Optional[Any],
) -> None:
    """Run factory pipeline with council pre-flight and post-build hooks."""
    # LLM Council pre-flight check (non-blocking)
    _preflight: Dict[str, Any] = {"passed": True, "score": 1.0, "reason": "skipped", "suggestions": []}
    try:
        from aether_os.core.council import PreFlightCouncil
        _council = PreFlightCouncil()
        # Cap the council call at 60s — if LLM is slow, skip it
        _preflight = await asyncio.wait_for(
            _council.run(raw_input=raw_input, domain=domain, org_id=org_id),
            timeout=60.0,
        )
        if not _preflight.get("passed", True):
            if os.environ.get("COUNCIL_STRICT_MODE", "false").lower() == "true":
                logger.warning(
                    "PreFlightCouncil STRICT: run %s rejected (score=%.2f): %s",
                    run_id, _preflight.get("score", 0.0), _preflight.get("reason", ""),
                )
                # Mark the run as rejected so the UI shows it clearly
                try:
                    from aether_os.core.db import get_session_factory as _gsf_rej
                    from aether_os.core.models import Run as _Run_rej
                    from sqlalchemy import update as _upd_rej
                    async with _gsf_rej()() as _s_rej:
                        await _s_rej.execute(
                            _upd_rej(_Run_rej).where(_Run_rej.id == run_id)
                            .values(
                                status="rejected",
                                message=f"PreFlightCouncil rejected: {_preflight.get('reason','')}",
                                council_preflight=_preflight,
                            )
                        )
                        await _s_rej.commit()
                except Exception as _rej_exc:
                    logger.warning("Failed to mark run as rejected: %s", _rej_exc)
                return  # Abort pipeline in strict mode
            logger.warning(
                "PreFlightCouncil: run %s did not pass (score=%.2f) — proceeding (non-strict): %s",
                run_id, _preflight.get("score", 0.0), _preflight.get("reason", ""),
            )
    except (asyncio.TimeoutError, Exception) as _ce:
        logger.warning("PreFlightCouncil skipped (timeout/error): %s", type(_ce).__name__)

    try:
        await factory.run(
            client_id=client_id,
            raw_input=raw_input,
            domain=domain,
            project_name=project_name,
            run_id=run_id,
            org_id=org_id,
            council_preflight=_preflight,
            github_url=github_url or None,
            designer_spec=designer_spec or {},
            tech_preferences=tech_preferences,
            model_preference=model_preference,
            priority=priority,
            codebase_mode=codebase_mode,
            existing_schema=existing_schema,
        )
    except Exception as exc:
        logger.error("Background factory run failed: %s", exc)

    # ── Post-completion hooks (non-fatal) ──────────────────────────────────────
    # 1. Persist quality score to runs table
    try:
        from aether_os.core.quality.metrics import score_project
        from aether_os.core.projects import get_project_manager
        from aether_os.core.db import get_session_factory as _gsf_qs
        from aether_os.core.models import Run as _Run_qs
        from sqlalchemy import update as _upd_qs
        _project_dir = get_project_manager().get_project_dir(run_id)
        if _project_dir.exists():
            _qscore = score_project(_project_dir)
            async with _gsf_qs()() as _s_qs:
                await _s_qs.execute(
                    _upd_qs(_Run_qs).where(_Run_qs.id == run_id)
                    .values(quality_score=int(_qscore.total))
                )
                await _s_qs.commit()
            logger.info("[post-build] quality_score=%d saved for run %s", _qscore.total, run_id)
    except Exception as _qse:
        logger.debug("[post-build] quality score persist skipped: %s", _qse)

    # 2. Record GlobalPattern aggregate learning
    try:
        from aether_os.core.quality.metrics import score_project as _sp2
        from aether_os.core.projects import get_project_manager as _gpm2
        from aether_os.core.db import get_session_factory as _gsf_gp2
        from aether_os.core.services.global_pattern_service import record_global_pattern
        _project_dir2 = _gpm2().get_project_dir(run_id)
        if _project_dir2.exists():
            _qscore2 = _sp2(_project_dir2)
            async with _gsf_gp2()() as _s_gp:
                await record_global_pattern(
                    run_id=run_id,
                    domain=domain or "general",
                    quality_score_total=float(_qscore2.total),
                    quality_details=_qscore2.details,
                    session=_s_gp,
                )
            logger.info("[post-build] GlobalPattern recorded domain=%s score=%.1f", domain, _qscore2.total)
    except Exception as _gpe:
        logger.debug("[post-build] GlobalPattern skipped: %s", _gpe)

    # 3. Learning loop — extract patterns from completed run
    if user_id and org_id:
        try:
            from aether_os.core.services import learning_service as _ls2
            from aether_os.core.db import get_session_factory as _gsf_ls
            async with _gsf_ls()() as _s_ls:
                await _ls2.extract_patterns_from_run(run_id, org_id, user_id, _s_ls)
            logger.info("[post-build] Learning patterns extracted for user %s", user_id)
        except Exception as _le:
            logger.debug("[post-build] Learning loop skipped: %s", _le)
