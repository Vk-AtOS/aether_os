"""
AetherOS — Factory Start Router
Extracted from factory_ops_router.py to keep that file under 400 lines.

Routes:
  POST /factory/start       — synchronous pipeline start (background task)
  POST /factory/estimate    — cost estimator (kept here, close to start logic)
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.policy_guard import enforce

logger = logging.getLogger(__name__)
router = APIRouter(tags=["factory"])


def _current_user():
    return Depends(get_current_user)


# ── Pydantic models ───────────────────────────────────────────────────────────

class FactoryStartRequest(BaseModel):
    """Intake schema for POST /factory/start.

    All new fields are Optional with safe defaults so existing callers that
    only send raw_input + domain continue to work without modification.
    """
    # protected_namespaces=() suppresses the PydanticUserWarning for the
    # model_preference field, which starts with "model_" (a Pydantic v2 reserved
    # prefix). The field name is intentional and not a Pydantic internal.
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    # Core fields (pre-existing)
    raw_input: Optional[str] = None
    requirement: Optional[str] = None  # legacy alias for raw_input
    domain: str = "general"
    project_name: Optional[str] = None
    github_url: str = ""
    designer_spec: Optional[Dict[str, Any]] = None
    production_country: Optional[str] = None
    compliance_flags: Optional[Dict[str, Any]] = None
    tech_preferences: Optional[Dict[str, Any]] = None
    model_preference: str = ""
    priority: str = "normal"
    codebase_mode: str = "new"
    existing_schema: Optional[Dict[str, Any]] = None
    client_id: Optional[str] = None

    # ── Q1 / Q4: New enrichment fields ───────────────────────────────────────
    # Each persona: {"name": str, "type": "customer"|"admin", "key_actions": [str]}
    user_personas: Optional[List[Dict[str, Any]]] = None
    has_customer_portal: Optional[bool] = None   # None = auto-detect from user_personas
    has_landing_page: bool = False               # generate a public marketing/landing page
    # Brand tokens: {"tagline": str, "primary_color": "#hex", "logo_text": str}
    app_brand: Optional[Dict[str, Any]] = None
    # Entities needing live updates: ["policy_alerts", "compliance_status", ...]
    realtime_features: Optional[List[str]] = None
    # Domain vocabulary examples: {"Policy": ["GDPR Article 5", "SOC2 CC6.1"]}
    seed_vocabulary: Optional[Dict[str, Any]] = None
    multi_tenancy: Optional[bool] = None   # top-level; also readable from designer_spec.features

    # ── Interactive Questionnaire fields ──────────────────────────────────────
    # mode: "autonomous" (default) skips questionnaire gates;
    #       "guided" pauses after each phase for respondent input.
    mode: str = "autonomous"
    # intake_answers: pre-filled answers for autonomous mode (keyed by question id)
    intake_answers: Dict[str, Any] = {}
    # respondent_email: external client email for guided mode link delivery
    respondent_email: Optional[str] = None
    # agency_name / agency_logo_url: white-label branding on questionnaire pages
    agency_name: Optional[str] = None
    agency_logo_url: Optional[str] = None


# ── Strong references prevent GC from silently killing in-flight tasks ────────
_background_tasks: set = set()


async def _check_db_run_limits(org_id: str) -> None:
    """DB-level concurrent run gate — authoritative (Redis may drift on crash).

    Raises 429 if org >= 3 active runs; 503 if platform >= 10.  Fails open on
    DB error so a slow DB at startup doesn't block all pipeline starts.
    """
    try:
        from aether_os.core.db import get_session_factory as _gsf_rl
        from aether_os.core.services.run_service import count_active_runs, _ORG_RUN_LIMIT, _PLATFORM_RUN_LIMIT
        async with _gsf_rl()() as _s:
            org_ct, plat_ct = await count_active_runs(_s, org_id)
        if org_ct >= _ORG_RUN_LIMIT:
            raise HTTPException(status_code=429, detail={
                "detail": "Rate limit: maximum 3 concurrent pipeline runs per organization. Please wait for a run to complete.",
                "running_count": org_ct, "limit": _ORG_RUN_LIMIT,
            })
        if plat_ct >= _PLATFORM_RUN_LIMIT:
            raise HTTPException(status_code=503, detail="Platform is at capacity. Please try again in a few minutes.")
    except HTTPException:
        raise
    except Exception as _e:
        logger.warning("DB run limit check failed (allowing request): %s", _e)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/factory/estimate")
async def estimate_cost(req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    """Estimate monthly hosting cost based on tech stack and domain."""
    domain = req.get("domain", "general")
    db = req.get("database", "postgresql")
    scale = req.get("scale", "small")  # small / medium / large
    base = {"small": 15, "medium": 45, "large": 120}.get(scale, 15)
    db_cost = {"postgresql": 20, "mongodb": 25, "sqlite": 0, "redis": 10}.get(db.lower(), 20)
    domain_mult = {"healthcare": 1.4, "fintech": 1.3, "saas": 1.2}.get(domain, 1.0)
    total = round((base + db_cost) * domain_mult)
    return {
        "estimated_monthly_usd": total,
        "range": f"${round(total * 0.8)}–${round(total * 1.4)}/month",
        "breakdown": {"compute": base, "database": db_cost, "extras": round(total - base - db_cost)},
        "note": "Estimate for a small VPS (2 vCPU / 4 GB RAM). Scale up for production traffic.",
    }


@router.post("/factory/start")
async def start_factory_run(
    req: FactoryStartRequest,
    request: Request,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Start a new factory pipeline run (10-phase path)."""
    from aether_os.orchestrator.factory_pipeline import get_factory
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    from aether_os.core.rate_limiter import get_rate_limiter
    from aether_os.gateway.routers.factory_run_background import (
        build_spec_preamble, run_compliance_precheck, run_pipeline_background,
    )
    from sqlalchemy import select
    import uuid as _uuid

    org_id = user.get("org_id")

    # ── Policy: org active, role, plan quota, concurrent runs (denials are ledgered) ──
    # Before rate limits so an org out of quota sees 402 (upgrade), not 429.
    # The atomic trial increment below still guards against TOCTOU races.
    await enforce("run.start", user)

    # ── Rate limiting ─────────────────────────────────────────────────────────
    _rl = get_rate_limiter()
    if not await _rl.check_factory_start(org_id):
        raise HTTPException(
            status_code=429,
            detail=f"Too many pipeline starts. Max {_rl.max_factory_starts_per_min} per minute per org.",
        )
    if not await _rl.check_hourly_starts(org_id):
        raise HTTPException(
            status_code=429,
            detail=f"Hourly pipeline limit reached ({_rl.max_starts_per_hour}/hr).",
        )
    if not await _rl.check_concurrent_runs(org_id):
        raise HTTPException(
            status_code=429,
            detail=f"Max concurrent runs reached ({_rl.max_concurrent_runs}). Wait for a run to complete.",
        )

    # ── DB-level per-org and global limits (authoritative — Redis may drift) ──
    await _check_db_run_limits(org_id)

    await _rl.record_factory_start(org_id)

    # B9: Atomic trial run check — single UPDATE prevents TOCTOU race
    from sqlalchemy import update as _sa_update
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Organisation).where(Organisation.id == org_id)
        result = await session.execute(stmt)
        org = result.scalar_one_or_none()

        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")

        # Storage limit check
        limit = -1
        if org.plan == "trial": limit = float(os.environ.get("STORAGE_LIMIT_MB_TRIAL", 500))
        elif org.plan == "pro": limit = float(os.environ.get("STORAGE_LIMIT_MB_PRO", 10000))
        if limit > 0 and org.storage_used_mb >= limit:
            raise HTTPException(
                status_code=402,
                detail={"error": "storage_limit_reached", "used_mb": org.storage_used_mb, "limit_mb": limit}
            )

        if org.plan == "trial":
            # Atomic increment — only succeeds if still under limit (B9: no TOCTOU)
            upd_result = await session.execute(
                _sa_update(Organisation)
                .where(Organisation.id == org_id)
                .where(Organisation.trial_runs_used < Organisation.trial_runs_limit)
                .values(trial_runs_used=Organisation.trial_runs_used + 1)
            )
            await session.commit()
            if upd_result.rowcount == 0:
                raise HTTPException(
                    status_code=402,
                    detail={"error": "trial_limit_reached", "upgrade_url": "/pricing"}
                )

    factory = get_factory()

    client_id = req.client_id or user.get("org_slug", "anonymous")
    raw_input = req.raw_input or req.requirement or ""
    domain = req.domain
    project_name = req.project_name
    github_url = (req.github_url or "").strip()
    designer_spec = req.designer_spec
    production_country = (req.production_country or "").strip().upper() or None
    compliance_flags = req.compliance_flags or {}
    tech_preferences = req.tech_preferences or {}
    model_preference = (req.model_preference or "").strip()
    priority = (req.priority or "normal").lower()
    codebase_mode = (req.codebase_mode or "new").lower()
    existing_schema = req.existing_schema

    # ── Q1 / Q4: New enrichment fields ────────────────────────────────────────
    user_personas = req.user_personas or []
    has_customer_portal = req.has_customer_portal   # None = auto-detect downstream
    has_landing_page = req.has_landing_page
    app_brand = req.app_brand or {}
    realtime_features = req.realtime_features or []
    seed_vocabulary = req.seed_vocabulary or {}
    # Promote multi_tenancy to top-level (also keep backward compat in designer_spec)
    _ds_multi = ((req.designer_spec or {}).get("features") or {}).get("multi_tenancy", False)
    multi_tenancy = req.multi_tenancy if req.multi_tenancy is not None else (_ds_multi or False)
    # ── Interactive questionnaire fields ──────────────────────────────────────
    run_mode = req.mode or "autonomous"
    intake_answers = req.intake_answers or {}
    respondent_email = req.respondent_email or None
    agency_name = req.agency_name or None
    agency_logo_url = req.agency_logo_url or None

    if not raw_input:
        raise HTTPException(status_code=400, detail="raw_input or requirement is required")

    # Prepend structured spec preamble when designer_spec is provided
    if designer_spec and isinstance(designer_spec, dict):
        try:
            raw_input = build_spec_preamble(designer_spec, existing_schema) + raw_input
        except Exception as _spec_exc:
            logger.warning("Failed to build designer_spec preamble: %s", _spec_exc)

    # Compliance pre-check — block embargoed countries, enforce jurisdiction
    if production_country:
        designer_spec = run_compliance_precheck(
            production_country=production_country,
            compliance_flags=compliance_flags,
            domain=domain,
            designer_spec=designer_spec or {},
        )

    # B7: Prompt injection guard — block jailbreak and shell injection attempts
    from aether_os.core.security.prompt_guard import guard as _guard
    _safe, _reason = _guard(raw_input)
    if not _safe:
        raise HTTPException(status_code=400, detail=_reason)

    # Pre-generate run_id and insert Run record immediately so the client
    # can poll /factory/runs/{run_id} without a 30s+ 404 window.
    run_id = str(_uuid.uuid4())
    user_id = user.get("sub")
    try:
        from aether_os.core.db import get_session_factory as _gsf_pre
        from aether_os.core.models import Run as _Run_pre
        import time as _time_pre
        async with _gsf_pre()() as _s_pre:
            _s_pre.add(_Run_pre(
                id=run_id,
                org_id=org_id,
                user_id=user_id,
                command=f"factory: {raw_input[:60]}",
                raw_input=raw_input,
                project_name=project_name,
                domain=domain,
                status="queued",
                started_at=_time_pre.time(),
            ))
            await _s_pre.commit()
    except Exception as _pre_exc:
        logger.warning("Pre-insert run record failed: %s", _pre_exc)

    # ── SQS queuing (when configured) vs. direct background execution ─────────
    from aether_os.core.queue.sqs_client import is_enabled as _sqs_enabled, send_pipeline_job
    _enriched_payload: Dict[str, Any] = {
        "client_id": client_id,
        "raw_input": raw_input,
        "domain": domain,
        "project_name": project_name,
        "org_id": org_id,
        "org_slug": org_id,
        "github_url": github_url or None,
        "designer_spec": designer_spec or {},
        "tech_preferences": tech_preferences,
        "model_preference": model_preference,
        "priority": priority,
        "codebase_mode": codebase_mode,
        "existing_schema": existing_schema,
        # Q1 / Q4: enrichment fields forwarded to orchestrator
        "user_personas": user_personas,
        "has_customer_portal": has_customer_portal,
        "has_landing_page": has_landing_page,
        "app_brand": app_brand,
        "realtime_features": realtime_features,
        "seed_vocabulary": seed_vocabulary,
        "multi_tenancy": multi_tenancy,
        # Interactive questionnaire fields
        "mode": run_mode,
        "intake_answers": intake_answers,
        "respondent_email": respondent_email,
        "agency_name": agency_name,
        "agency_logo_url": agency_logo_url,
    }
    if _sqs_enabled():
        _queued = send_pipeline_job(run_id, _enriched_payload)
        if _queued:
            try:
                from aether_os.core.db import get_session_factory as _gsf_q
                from aether_os.core.models import Run as _Run_q
                from sqlalchemy import update as _upd_q
                async with _gsf_q()() as _s_q:
                    await _s_q.execute(_upd_q(_Run_q).where(_Run_q.id == run_id).values(status="queued"))
                    await _s_q.commit()
            except Exception as _qe:
                logger.warning("SQS queue status update failed: %s", _qe)
            return {"run_id": run_id, "status": "queued", "message": f"Pipeline queued (SQS): {raw_input[:60]}"}
        else:
            logger.warning("SQS send failed for run %s — falling back to direct execution", run_id)

    _t = asyncio.create_task(run_pipeline_background(
        factory=factory,
        run_id=run_id,
        client_id=client_id,
        raw_input=raw_input,
        domain=domain,
        project_name=project_name,
        org_id=org_id,
        user_id=user_id,
        github_url=github_url or None,
        designer_spec=designer_spec or {},
        tech_preferences=tech_preferences,
        model_preference=model_preference,
        priority=priority,
        codebase_mode=codebase_mode,
        existing_schema=existing_schema,
        user_personas=user_personas,
        has_customer_portal=has_customer_portal,
        has_landing_page=has_landing_page,
        app_brand=app_brand,
        realtime_features=realtime_features,
        seed_vocabulary=seed_vocabulary,
        multi_tenancy=multi_tenancy,
        mode=run_mode,
        intake_answers=intake_answers,
        respondent_email=respondent_email,
        agency_name=agency_name,
        agency_logo_url=agency_logo_url,
    ))
    _background_tasks.add(_t)
    _t.add_done_callback(_background_tasks.discard)

    return {
        "run_id": run_id,
        "status": "started",
        "message": f"Pipeline started for: {raw_input[:60]}",
    }
