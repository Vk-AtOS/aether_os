"""
AetherOS — System Info Router
GET  /health/observability
GET  /health/sla
GET  /system/costs
GET  /pricing
GET  /system/feature-flags
POST /system/feature-flags/{flag}
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


def _current_user():
    return Depends(get_current_user)


@router.get("/health/observability")
async def health_observability() -> Dict[str, Any]:
    """Observability health — LangSmith status and today's trace count."""
    from aether_os.core.telemetry.langsmith_tracer import get_status
    return get_status()


@router.get("/health/sla")
async def health_sla(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    """T4-10: SLA metrics — uptime window, run completion rate, p50/p95 duration."""
    import time as _t_sla
    org_id = user["org_id"]
    window_days = 30
    since = _t_sla.time() - window_days * 86400
    try:
        from aether_os.core.db import get_session_factory as _gsf_sla
        from aether_os.core.models import Run as _Run_sla
        from sqlalchemy import select as _sel_sla
        async with _gsf_sla()() as _sess:
            q = _sel_sla(_Run_sla).where(
                _Run_sla.org_id == org_id,
                _Run_sla.started_at >= since,
            )
            rows = (await _sess.execute(q)).scalars().all()
    except Exception as exc:
        logger.debug("health_sla: DB query failed: %s", exc)
        rows = []

    total = len(rows)
    completed = sum(1 for r in rows if getattr(r, "status", "") == "completed")
    failed = sum(1 for r in rows if getattr(r, "status", "") in ("failed", "timeout"))
    durations = []
    for r in rows:
        if getattr(r, "finished_at", None) and getattr(r, "started_at", None):
            try:
                d = float(r.finished_at) - float(r.started_at)
                if d > 0:
                    durations.append(d)
            except Exception as exc:
                logger.debug("health_sla: duration parse error: %s", exc)
    durations.sort()

    def percentile(data, pct):
        if not data:
            return None
        idx = max(0, int(len(data) * pct / 100) - 1)
        return round(data[idx], 1)

    completion_rate = round(completed / total, 4) if total > 0 else None
    # uptime_sla_met is None when there are no completed runs — callers must
    # render this as "N/A" rather than "Not Met" to avoid false negatives.
    uptime_sla_met = (completion_rate >= 0.995) if completion_rate is not None else None
    return {
        "window_days": window_days,
        "total_runs": total,
        "completed_runs": completed,
        "failed_runs": failed,
        "completion_rate": completion_rate,
        "uptime_sla_met": uptime_sla_met,
        "duration_p50_s": percentile(durations, 50),
        "duration_p95_s": percentile(durations, 95),
        "sla_tier": user.get("plan", "trial"),
        "sla_target": {
            "trial": "best-effort",
            "pro": "99.0%",
            "enterprise": "99.9%",
        }.get(user.get("plan", "trial"), "best-effort"),
    }


@router.get("/system/costs")
async def system_costs(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Aggregate cost summary for the current org."""
    org_id = user["org_id"]
    plan = user.get("plan", "trial")

    try:
        from aether_os.core.llm.budget import get_budget_manager, _PLAN_BUDGETS
        bm = get_budget_manager()
        usage = await bm.get_usage(org_id)
        history = await bm.get_cost_report(org_id, months=3)
        budget_tokens = _PLAN_BUDGETS.get(plan, 500_000)
        budget_used_pct = round(usage["total_tokens"] / max(budget_tokens, 1) * 100, 1)
    except Exception as exc:
        logger.debug("system_costs: budget manager unavailable: %s", exc)
        usage = {"input_tokens": 0, "output_tokens": 0, "runs": 0,
                 "estimated_cost_usd": 0.0, "total_tokens": 0,
                 "cache_hits": 0, "cache_misses": 0}
        history = []
        budget_tokens = 500_000
        budget_used_pct = 0.0

    try:
        from aether_os.core.llm.cache import get_llm_cache
        cache_stats = await get_llm_cache().get_stats()
    except Exception as exc:
        logger.debug("system_costs: cache stats unavailable: %s", exc)
        cache_stats = {"total_entries": 0, "total_hits": 0, "daily": []}

    runs = usage["runs"] or 1
    return {
        "this_month": {
            "estimated_cost_usd": round(usage["estimated_cost_usd"], 4),
            "cost_per_run": round(usage["estimated_cost_usd"] / runs, 4),
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "runs": usage["runs"],
            "cache_hits": usage["cache_hits"],
            "cache_misses": usage["cache_misses"],
            "cache_hit_rate": round(
                usage["cache_hits"] / max(usage["cache_hits"] + usage["cache_misses"], 1), 3
            ),
            "budget_tokens": budget_tokens,
            "budget_used_pct": budget_used_pct,
        },
        "tokens_today": usage["total_tokens"],
        "history": history,
        "cache": cache_stats,
        "targets": {
            "cost_per_run_target": 0.35,
            "cost_per_run_current": round(usage["estimated_cost_usd"] / runs, 4),
            "reduction_needed_pct": max(0, round(
                (1 - 0.35 / max(usage["estimated_cost_usd"] / runs, 0.35)) * 100, 1
            )),
        },
    }


@router.get("/pricing")
async def pricing():
    """Return pricing information."""
    from fastapi.responses import HTMLResponse
    html = """
    <html>
    <head><title>AetherOS Pricing</title></head>
    <body style="font-family: sans-serif; padding: 40px; line-height: 1.6;">
        <h1>AetherOS Plans</h1>
        <div style="display: flex; gap: 20px;">
            <div style="border: 1px solid #ccc; padding: 20px; border-radius: 8px; flex: 1;">
                <h2>Trial</h2>
                <p>Free</p>
                <ul>
                    <li>3 Pipeline Runs</li>
                    <li>Standard Agents</li>
                </ul>
            </div>
            <div style="border: 1px solid #007bff; padding: 20px; border-radius: 8px; flex: 1; background: #f0f7ff;">
                <h2>Pro</h2>
                <p>&#8377;2,00,000 One-time</p>
                <ul>
                    <li>Unlimited Runs</li>
                    <li>Priority Support</li>
                    <li>Custom Agents</li>
                </ul>
            </div>
            <div style="border: 1px solid #ccc; padding: 20px; border-radius: 8px; flex: 1;">
                <h2>Enterprise</h2>
                <p>Custom</p>
                <ul>
                    <li>On-premise deployment</li>
                    <li>SLA Guarantees</li>
                    <li>Dedicated Infrastructure</li>
                </ul>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.get("/system/feature-flags")
async def list_feature_flags(user: Dict[str, Any] = Depends(get_current_user)):
    """Return current platform feature flag states (admin use)."""
    from aether_os.core.feature_flags import flags
    return {"flags": flags.all_flags(), "source": "growthbook+env+defaults"}


@router.post("/system/feature-flags/{flag}")
async def set_feature_flag(
    flag: str, body: dict = {}, user: Dict[str, Any] = Depends(get_current_user)
):
    """Override a platform feature flag at runtime via env var (platform operator only).

    The flag lives in this process's environment, so it changes behaviour for every
    organisation: an org's own owner or admin must not be able to set it.
    """
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Platform operator access required")
    from aether_os.core.feature_flags import flags
    if flag not in flags.all_flags():
        raise HTTPException(status_code=404, detail="Unknown feature flag")
    value = body.get("enabled", True)
    key = f"FEATURE_{flag.upper()}"
    os.environ[key] = "true" if value else "false"
    return {"flag": flag, "enabled": value, "env_key": key}
