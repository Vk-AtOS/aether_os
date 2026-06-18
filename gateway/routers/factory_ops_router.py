"""
AetherOS — Factory Ops Router
Extracted from gateway/api.py (inline routes → APIRouter).

Routes (core run operations):
  GET  /templates
  POST /factory/estimate
  POST /factory/start
  GET  /pipeline/status/{run_id}
  POST /pipeline/approve/{ticket_id}

See also:
  factory_intake_router.py   — upload/fetch/import routes
  factory_analytics_router.py — search, quality-trend, deployments
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["factory"])


def _current_user():
    return Depends(get_current_user)


# ── Pydantic models ───────────────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    ticket_id: str
    decision: str  # "approve" | "deny"
    reason: Optional[str] = None


# ── Strong references prevent GC from silently killing in-flight tasks ────────
_background_tasks: set = set()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/pipeline/status/{run_id}")
async def get_pipeline_status(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get status of a pipeline run."""
    from aether_os.core.audit.ledger import get_ledger
    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return detail


@router.post("/pipeline/approve/{ticket_id}")
async def approve_action(
    ticket_id: str,
    req: ApproveRequest,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Approve or deny a human-gated pipeline action via DecisionEngine."""
    from aether_os.core.decisions.decision_engine import get_decision_engine
    engine = get_decision_engine()
    approved = req.decision in ("approve", "approved", "yes", True)
    try:
        decision = await engine.resolve(
            decision_id=ticket_id,
            org_id=user.get("org_id", ""),
            approved=approved,
            choice=req.reason,
        )
        return {
            "ticket_id": ticket_id,
            "decision":  "approved" if approved else "denied",
            "decided_by": user.get("sub"),
            "reason":    req.reason,
            "timestamp": time.time(),
            "status":    decision.status if decision else "resolved",
        }
    except LookupError:
        # Decision not pending in engine — treat as already resolved
        return {
            "ticket_id": ticket_id,
            "decision":  "approved" if approved else "denied",
            "decided_by": user.get("sub"),
            "timestamp": time.time(),
            "status": "already_resolved",
        }


@router.get("/templates")
async def list_templates(user: Dict[str, Any] = _current_user()):
    """Return available project templates."""
    return {"templates": [
        {"id": "saas", "name": "SaaS App", "description": "Multi-tenant SaaS with auth, billing, and dashboard", "domain": "saas", "icon": "🏢"},
        {"id": "ecommerce", "name": "E-Commerce", "description": "Product catalog, cart, orders, and payments", "domain": "ecommerce", "icon": "🛒"},
        {"id": "dashboard", "name": "Analytics Dashboard", "description": "Data visualisation, charts, and KPI tracking", "domain": "analytics", "icon": "📊"},
        {"id": "api", "name": "REST API", "description": "Clean REST API with auth, rate limiting, and docs", "domain": "api", "icon": "⚡"},
        {"id": "cms", "name": "CMS / Blog", "description": "Content management with rich text editor and media", "domain": "cms", "icon": "✍️"},
        {"id": "social", "name": "Social Platform", "description": "User profiles, posts, follows, and notifications", "domain": "social", "icon": "👥"},
        {"id": "marketplace", "name": "Marketplace", "description": "Two-sided marketplace with listings and transactions", "domain": "marketplace", "icon": "🏪"},
        {"id": "healthcare", "name": "Healthcare", "description": "Patient records, appointments, and HIPAA compliance", "domain": "healthcare", "icon": "🏥"},
        {"id": "fintech", "name": "FinTech", "description": "Transactions, wallets, and financial reporting", "domain": "fintech", "icon": "💳"},
        {"id": "iot", "name": "IoT Dashboard", "description": "Device management, telemetry streams, and alerts", "domain": "iot", "icon": "📡"},
        {"id": "lms", "name": "Learning Management", "description": "Courses, lessons, quizzes, and student progress", "domain": "education", "icon": "🎓"},
        {"id": "custom", "name": "Custom", "description": "Describe your own requirements from scratch", "domain": "general", "icon": "🛠️"},
    ]}


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
    req: Dict[str, Any],
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

    client_id = req.get("client_id", user.get("org_slug", "anonymous"))
    raw_input = req.get("raw_input", req.get("requirement", ""))
    domain = req.get("domain", "general")
    project_name = req.get("project_name")
    github_url = req.get("github_url", "").strip()
    designer_spec = req.get("designer_spec")
    production_country = (req.get("production_country") or "").strip().upper() or None
    compliance_flags = req.get("compliance_flags") or {}
    tech_preferences = req.get("tech_preferences") or {}
    model_preference = (req.get("model_preference") or "").strip()
    priority = (req.get("priority") or "normal").lower()
    codebase_mode = (req.get("codebase_mode") or "new").lower()
    existing_schema = req.get("existing_schema")

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
    if _sqs_enabled():
        _queued = send_pipeline_job(run_id, {
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
        })
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
    ))
    _background_tasks.add(_t)
    _t.add_done_callback(_background_tasks.discard)

    return {
        "run_id": run_id,
        "status": "started",
        "message": f"Pipeline started for: {raw_input[:60]}",
    }
