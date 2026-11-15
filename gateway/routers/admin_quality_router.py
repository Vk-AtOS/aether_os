"""
AetherOS — Admin Quality Router
=================================
Quality assurance visibility endpoints for the pipeline. Split from
admin_platform_router.py because adding these endpoints would have exceeded
the 400-line router limit.

Routes
------
  GET  /admin/platform/quality-metrics
  GET  /admin/platform/run-costs
  GET  /admin/platform/phase-latency
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"])


def _current_user():
    return Depends(get_current_user)


# Error registry — imported at module level with graceful fallback
try:
    from aether_os.core.error_registry import get_registry as _get_registry
    _registry_available = True
except ImportError:
    _registry_available = False
    logger.warning("admin_quality_router: core.error_registry not available — error categories will be omitted")


@router.get("/admin/platform/quality-metrics")
async def quality_metrics(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """
    Return a JSON dashboard of pipeline quality.

    Includes recent run success rate, per-phase confidence averages (parsed from
    run JSON), top error categories from the error registry, and a count of
    low-confidence runs.  Requires admin or superadmin role.
    """
    if user.get("role") not in ("owner", "admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select

    org_id = user["org_id"]
    sf = get_session_factory()

    # ── Fetch recent 50 runs ─────────────────────────────────────────────────
    recent_runs: List[Run] = []
    try:
        async with sf() as session:
            recent_runs = (await session.execute(
                select(Run)
                .where(Run.org_id == org_id)
                .order_by(Run.started_at.desc())
                .limit(50)
            )).scalars().all()
    except Exception as exc:
        logger.warning("admin_quality_router: quality-metrics DB query failed: %s", exc)

    total = len(recent_runs)
    succeeded = sum(1 for r in recent_runs if r.status in ("completed", "passed"))
    failed = sum(1 for r in recent_runs if r.status in ("failed", "error"))
    success_rate = round(succeeded / total, 4) if total else 0.0

    # ── Phase confidence averages (from checkpoint_data JSON) ────────────────
    phase_confidence_sums: Dict[str, List[float]] = {}
    low_confidence_runs = 0
    LOW_CONF_THRESHOLD = 0.6

    for run in recent_runs:
        # checkpoint_data may hold accumulated_context with phase_confidence dict
        checkpoint = run.checkpoint_data or {}
        acc_ctx = checkpoint.get("accumulated_context", {})
        phase_conf = acc_ctx.get("phase_confidence", {})

        if not phase_conf and run.phases:
            # phases JSON may directly hold per-phase confidence keys
            phase_conf = {
                k: v for k, v in run.phases.items()
                if isinstance(v, (int, float)) and 0.0 <= v <= 1.0
            }

        if phase_conf:
            run_confidences: List[float] = []
            for phase_name, conf_val in phase_conf.items():
                if isinstance(conf_val, (int, float)):
                    phase_confidence_sums.setdefault(phase_name, []).append(float(conf_val))
                    run_confidences.append(float(conf_val))
            avg = sum(run_confidences) / len(run_confidences) if run_confidences else 1.0
            if avg < LOW_CONF_THRESHOLD:
                low_confidence_runs += 1

    phase_confidence_averages: Optional[Dict[str, float]] = None
    if phase_confidence_sums:
        phase_confidence_averages = {
            phase: round(sum(vals) / len(vals), 4)
            for phase, vals in phase_confidence_sums.items()
        }

    # ── Top error categories from registry ──────────────────────────────────
    top_error_categories: List[Dict[str, Any]] = []
    if _registry_available:
        try:
            reg = _get_registry()
            summary = reg.get_summary()
            by_cat = summary.get("by_category", {})
            sorted_cats = sorted(by_cat.items(), key=lambda kv: kv[1]["count"], reverse=True)
            top_error_categories = [
                {"category": cat, "count": info["count"], "last_seen": info.get("last_seen")}
                for cat, info in sorted_cats[:10]
            ]
        except Exception as exc:
            logger.warning("admin_quality_router: error registry summary failed: %s", exc)

    return {
        "recent_runs": {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": success_rate,
        },
        "phase_confidence_averages": phase_confidence_averages,
        "top_error_categories": top_error_categories,
        "low_confidence_runs": low_confidence_runs,
    }


@router.get("/admin/platform/run-costs")
async def run_costs(
    run_id: Optional[str] = Query(None, description="Specific run ID; omit to see org-level totals"),
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """
    Return cost data from LLMCallRecord rows.  If token usage has been tracked
    via the llm_call_records table, returns per-run or aggregate totals with
    estimated Claude Sonnet pricing ($3/M input tokens, $15/M output tokens).
    If no data is available, returns a clear status rather than fake numbers.
    Requires admin or superadmin role.
    """
    if user.get("role") not in ("owner", "admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    from aether_os.core.db import get_session_factory
    from aether_os.core.models import LLMCallRecord
    from sqlalchemy import select

    org_id = user["org_id"]
    sf = get_session_factory()

    # Claude Sonnet pricing constants (USD per million tokens)
    PRICE_INPUT_PER_M = 3.0
    PRICE_OUTPUT_PER_M = 15.0

    try:
        async with sf() as session:
            stmt = select(LLMCallRecord).where(LLMCallRecord.org_id == org_id)
            if run_id:
                stmt = stmt.where(LLMCallRecord.project_id == run_id)
            stmt = stmt.order_by(LLMCallRecord.created_at.desc()).limit(500)
            records = (await session.execute(stmt)).scalars().all()
    except Exception as exc:
        logger.warning("admin_quality_router: run-costs DB query failed: %s", exc)
        return {"status": "no_cost_data", "message": "Token usage tracking not yet enabled"}

    if not records:
        return {"status": "no_cost_data", "message": "Token usage tracking not yet enabled"}

    # Aggregate by project_id (run)
    runs_map: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        pid = rec.project_id
        if pid not in runs_map:
            runs_map[pid] = {"input_tokens": 0, "output_tokens": 0, "call_count": 0, "stored_cost_usd": 0.0}
        runs_map[pid]["input_tokens"] += rec.input_tokens
        runs_map[pid]["output_tokens"] += rec.output_tokens
        runs_map[pid]["call_count"] += 1
        runs_map[pid]["stored_cost_usd"] += rec.cost_usd

    run_summaries = []
    total_input = 0
    total_output = 0
    for pid, agg in runs_map.items():
        inp = agg["input_tokens"]
        out = agg["output_tokens"]
        estimated = round(inp / 1_000_000 * PRICE_INPUT_PER_M + out / 1_000_000 * PRICE_OUTPUT_PER_M, 6)
        total_input += inp
        total_output += out
        run_summaries.append({
            "run_id": pid,
            "input_tokens": inp,
            "output_tokens": out,
            "call_count": agg["call_count"],
            "estimated_cost_usd": estimated,
            "stored_cost_usd": round(agg["stored_cost_usd"], 6),
        })

    org_estimated = round(
        total_input / 1_000_000 * PRICE_INPUT_PER_M +
        total_output / 1_000_000 * PRICE_OUTPUT_PER_M,
        4,
    )

    return {
        "status": "ok",
        "pricing_note": "Claude Sonnet: $3/M input, $15/M output tokens",
        "org_totals": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "estimated_cost_usd": org_estimated,
            "run_count": len(runs_map),
        },
        "runs": run_summaries,
    }


@router.get("/admin/platform/phase-latency")
async def phase_latency(
    run_id: Optional[str] = Query(None, description="Specific run ID; omit for aggregate across recent runs"),
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """
    Return per-phase latency data.  Uses the phase_completions table which stores
    duration_s per phase per run.  Falls back to checkpoint_data phase timings if
    no phase_completions rows exist.  Requires admin or superadmin role.
    """
    if user.get("role") not in ("owner", "admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run, PhaseCompletion
    from sqlalchemy import select

    org_id = user["org_id"]
    sf = get_session_factory()

    # ── Try phase_completions table first (most reliable source) ─────────────
    phase_durations: Dict[str, List[float]] = {}
    try:
        async with sf() as session:
            if run_id:
                # For a specific run, verify org membership first
                run_row = (await session.execute(
                    select(Run).where(Run.id == run_id, Run.org_id == org_id)
                )).scalar_one_or_none()
                if not run_row:
                    raise HTTPException(status_code=404, detail="Run not found")
                pc_rows = (await session.execute(
                    select(PhaseCompletion).where(PhaseCompletion.run_id == run_id)
                )).scalars().all()
            else:
                # Aggregate across recent 50 completed runs for this org
                run_ids_rows = (await session.execute(
                    select(Run.id)
                    .where(Run.org_id == org_id, Run.status.in_(["completed", "passed"]))
                    .order_by(Run.started_at.desc())
                    .limit(50)
                )).scalars().all()
                if run_ids_rows:
                    pc_rows = (await session.execute(
                        select(PhaseCompletion).where(PhaseCompletion.run_id.in_(run_ids_rows))
                    )).scalars().all()
                else:
                    pc_rows = []

            for pc in pc_rows:
                if pc.duration_s is not None and pc.duration_s > 0:
                    phase_durations.setdefault(pc.phase_name, []).append(pc.duration_s)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("admin_quality_router: phase-latency PC query failed: %s", exc)

    if not phase_durations:
        # Nothing in phase_completions — try checkpoint_data for the specific run
        if run_id:
            try:
                async with sf() as session:
                    run_row = (await session.execute(
                        select(Run).where(Run.id == run_id, Run.org_id == org_id)
                    )).scalar_one_or_none()
                if run_row and run_row.checkpoint_data:
                    timings = run_row.checkpoint_data.get("phase_timings", {})
                    for phase_name, dur in timings.items():
                        if isinstance(dur, (int, float)) and dur > 0:
                            phase_durations.setdefault(phase_name, []).append(float(dur))
            except Exception as exc:
                logger.warning("admin_quality_router: checkpoint_data fallback failed: %s", exc)

    if not phase_durations:
        return {"status": "insufficient_data", "message": "No phase latency data found in phase_completions or checkpoint_data"}

    # ── Compute avg and p95 per phase ────────────────────────────────────────
    def _p95(vals: List[float]) -> float:
        sorted_vals = sorted(vals)
        idx = max(0, int(len(sorted_vals) * 0.95) - 1)
        return round(sorted_vals[idx], 2)

    phases_out = [
        {
            "phase": phase,
            "sample_count": len(vals),
            "avg_seconds": round(sum(vals) / len(vals), 2),
            "p95_seconds": _p95(vals),
            "min_seconds": round(min(vals), 2),
            "max_seconds": round(max(vals), 2),
        }
        for phase, vals in sorted(phase_durations.items())
    ]

    return {
        "status": "ok",
        "scope": f"run:{run_id}" if run_id else f"org:{org_id} (last 50 completed runs)",
        "phases": phases_out,
    }
