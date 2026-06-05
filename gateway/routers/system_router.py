"""
AetherOS — System Router
GET /system/health
GET /health/observability
GET /health/sla
GET /system/costs
GET /pricing
GET /system/metrics
"""
from __future__ import annotations

import logging
import os
import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


def _current_user():
    return Depends(get_current_user)


@router.get("/system/metrics")
async def system_metrics() -> Dict[str, Any]:
    """System resource metrics — CPU, memory, disk, Redis, DB, pipeline."""
    import time as _time
    result: Dict[str, Any] = {"timestamp": _time.time()}

    # System resources
    try:
        import psutil as _ps
        loop = asyncio.get_running_loop()
        cpu_pct = await loop.run_in_executor(None, lambda: _ps.cpu_percent(interval=0.2))
        vm = _ps.virtual_memory()
        du = _ps.disk_usage("/")
        result["system"] = {
            "cpu_pct":   round(cpu_pct, 1),
            "mem_pct":   round(vm.percent, 1),
            "mem_used_mb": round(vm.used / 1024 / 1024),
            "mem_total_mb": round(vm.total / 1024 / 1024),
            "disk_pct":  round(du.percent, 1),
            "disk_free_gb": round(du.free / 1024 / 1024 / 1024, 1),
            "swap_pct":  round(_ps.swap_memory().percent, 1),
            "load_1m":   round(_ps.getloadavg()[0], 2),
            "load_5m":   round(_ps.getloadavg()[1], 2),
            "cpu_cores": _ps.cpu_count(),
            "uptime_sec": int(_time.time() - _ps.boot_time()),
        }
    except Exception as _e:
        result["system"] = {"error": str(_e)}

    # Redis
    try:
        import redis.asyncio as _redis_mod
        _r = _redis_mod.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
        info = await _r.info("all")
        await _r.aclose()
        result["redis"] = {
            "used_memory_human": info.get("used_memory_human"),
            "connected_clients": info.get("connected_clients"),
            "uptime_in_seconds": info.get("uptime_in_seconds"),
            "keyspace_hits":     info.get("keyspace_hits", 0),
            "keyspace_misses":   info.get("keyspace_misses", 0),
            "instantaneous_ops_per_sec": info.get("instantaneous_ops_per_sec", 0),
        }
    except Exception:
        result["redis"] = {"status": "unavailable"}

    # Database — run counts and pool info
    try:
        from aether_os.core.db import get_session_factory as _gsf_m
        from sqlalchemy import text as _text_m
        async with _gsf_m()() as _s_m:
            rows = (await _s_m.execute(_text_m(
                "SELECT status, COUNT(*) FROM runs GROUP BY status"
            ))).fetchall()
        run_counts = {r[0]: r[1] for r in rows}
        result["pipeline"] = {
            "runs_total":     sum(run_counts.values()),
            "runs_completed": run_counts.get("completed", 0),
            "runs_running":   run_counts.get("running", 0),
            "runs_failed":    run_counts.get("failed", 0) + run_counts.get("interrupted", 0),
        }
    except Exception:
        result["pipeline"] = {}

    # LLM cost tracking — query DB for today's totals (persists across restarts)
    try:
        from aether_os.core.db import get_session_factory as _gsf_llm
        from aether_os.core.models import LLMCallRecord as _LCR
        from sqlalchemy import select as _sel_llm, func as _func_llm
        import time as _time_llm
        _today_start = float(int(_time_llm.time() // 86400) * 86400)
        async with _gsf_llm()() as _sess_llm:
            _row = (await _sess_llm.execute(
                _sel_llm(
                    _func_llm.count(_LCR.id),
                    _func_llm.coalesce(_func_llm.sum(_LCR.input_tokens), 0),
                    _func_llm.coalesce(_func_llm.sum(_LCR.output_tokens), 0),
                ).where(_LCR.created_at >= _today_start)
            )).one()
        result["llm"] = {
            "calls_today":       int(_row[0]),
            "prompt_tokens":     int(_row[1]),
            "completion_tokens": int(_row[2]),
            "provider":          os.environ.get("PRIMARY_LLM", "unknown"),
        }
    except Exception:
        try:
            from aether_os.core.llm.client import _cost_registry
            result["llm"] = {
                "calls_today":        _cost_registry.get("calls", 0),
                "prompt_tokens":      _cost_registry.get("prompt_tokens", 0),
                "completion_tokens":  _cost_registry.get("completion_tokens", 0),
                "provider":           os.environ.get("PRIMARY_LLM", "unknown"),
            }
        except Exception:
            result["llm"] = {}

    # API latency (simple self-ping)
    try:
        import httpx as _httpx
        import time as _time2
        t0 = _time2.monotonic()
        async with _httpx.AsyncClient() as _hc:
            await _hc.get("http://localhost:8000/health", timeout=2.0)
        result["latency_ms"] = round((_time2.monotonic() - t0) * 1000)
    except Exception:
        result["latency_ms"] = 0

    return result


@router.get("/system/health")
async def system_health(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """System health check with LLM provider status."""
    import httpx as _httpx

    anthropic_available = bool(os.environ.get("ANTHROPIC_API_KEY"))
    gemini_available = bool(os.environ.get("GOOGLE_API_KEY"))
    openrouter_available = bool(os.environ.get("OPENROUTER_API_KEY"))

    # Check Ollama with 2-second timeout
    ollama_available = False
    try:
        async with _httpx.AsyncClient(timeout=2.0) as _http:
            resp = await _http.get("http://localhost:11434/api/tags")
            ollama_available = resp.status_code == 200
    except Exception:
        ollama_available = False

    any_llm = anthropic_available or gemini_available or ollama_available or openrouter_available

    # Determine active LLM provider from singleton or env
    from aether_os.core.llm.client import get_llm_client
    client = get_llm_client()
    active_provider = client.last_provider or os.environ.get("PRIMARY_LLM", "none")

    # Model router routing status
    routing: dict = {}
    try:
        from aether_os.core.model_router import get_router as _get_router
        routing = _get_router().get_status()
    except Exception:
        pass

    status = "healthy"
    message = "All systems operational."

    bedrock_available = bool(
        os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    if bedrock_available:
        _bm_heavy = os.environ.get("BEDROCK_MODEL_HEAVY", "us.anthropic.claude-sonnet-4-6")
        status = "healthy"
        message = f"Running on Amazon Bedrock ({_bm_heavy})."
    elif openrouter_available and not anthropic_available and not gemini_available and not ollama_available:
        status = "ok"
        message = "Running on OpenRouter (configured)."
    elif ollama_available and not anthropic_available and not gemini_available:
        status = "ok"
        message = "Running on local Ollama (configured)."
    elif not any_llm:
        status = "warning"
        message = "No LLM providers available. System will fail to process tasks."

    llm_display = active_provider
    if active_provider in ("openrouter", "none") and openrouter_available:
        from aether_os.core.llm.openrouter_client import select_openrouter_model as _sel_or
        llm_display = f"openrouter ({_sel_or('code_generation')})"
    elif active_provider == "ollama":
        llm_display = f"ollama ({os.environ.get('OLLAMA_MODEL', 'qwen2.5-coder:7b')})"

    # Real database health check
    db_status = "unhealthy"
    try:
        from aether_os.core.db import get_session_factory as _gsf_h
        from sqlalchemy import text as _ht
        async with _gsf_h()() as _sh:
            await _sh.execute(_ht("SELECT 1"))
        db_status = "healthy"
    except Exception:
        status = "degraded"
        message = "Database unreachable."

    # Real Redis/memory-store health check
    redis_status = "unavailable"
    try:
        from aether_os.core.pipeline_state import get_redis as _gr
        _r = await _gr()
        if _r:
            await _r.ping()
            redis_status = "healthy"
    except Exception:
        pass

    # Disk space check (warn if < 10% free on home partition)
    import shutil as _shutil
    try:
        _disk = _shutil.disk_usage(str(os.path.expanduser("~")))
        _free_pct = _disk.free / _disk.total * 100
        disk_status = "healthy" if _free_pct > 10 else "warning"
    except Exception:
        _free_pct = None
        disk_status = "unknown"

    # Uptime from process start
    import time as _time
    try:
        import psutil as _psu
        _proc = _psu.Process()
        _uptime_secs = int(_time.time() - _proc.create_time())
    except Exception:
        _uptime_secs = None

    # DB pool size
    _pool_size = None
    try:
        from aether_os.core.db import get_engine as _ge
        _eng = _ge()
        _pool_size = getattr(getattr(_eng, "pool", None), "size", lambda: None)()
    except Exception:
        pass

    # Sandbox — check docker socket availability
    import subprocess as _sp
    _sandbox_status = "not_configured"
    _sandbox_engine = "none"
    try:
        _docker_res = _sp.run(["docker", "info"], capture_output=True, timeout=3)
        if _docker_res.returncode == 0:
            _sandbox_status = "ok"
            _sandbox_engine = "docker"
    except Exception:
        pass

    # Workloop monitor status
    _workloop_status: dict = {}
    try:
        from aether_os.core.workloop_monitor import get_workloop_monitor as _gwm
        _workloop_status = _gwm().get_status()
    except Exception:
        pass

    return {
        "status": status,
        "message": message,
        # LLM fields — both naming conventions for compatibility
        "llm": "healthy" if any_llm else "unavailable",
        "provider": "healthy" if any_llm else "unavailable",
        "llm_provider": llm_display,
        "active_provider": active_provider,
        "active_model": routing.get("active_model") or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", ""),
        "anthropic_available": anthropic_available,
        "gemini_available": gemini_available,
        "ollama_available": ollama_available,
        "openrouter_available": openrouter_available,
        "fallback_count_today": routing.get("fallback_count_today", 0),
        "model_availability": routing.get("model_availability", {}),
        # System info
        "version": "1.0.0",
        "environment": os.environ.get("ENVIRONMENT", "development"),
        "env": os.environ.get("ENVIRONMENT", "development"),
        "uptime": _uptime_secs,
        # Database
        "database": db_status,
        "db_pool_size": _pool_size,
        # Redis — both naming conventions
        "redis": redis_status,
        "cache": redis_status,
        "memory_store": redis_status,
        # Sandbox — check docker availability
        "sandbox": _sandbox_status,
        "sandbox_engine": _sandbox_engine,
        "active_sandboxes": 0,
        # Network
        "network": "healthy",
        # Disk
        "disk_free_pct": round(_free_pct, 1) if _free_pct is not None else None,
        "disk_status": disk_status,
        # Self-healing workloop
        "workloop_monitor": {
            "running": _workloop_status.get("running", False),
            "check_count": _workloop_status.get("check_count", 0),
            "error_count": _workloop_status.get("error_count", 0),
            "last_findings": len(_workloop_status.get("last_findings", [])),
            "auto_fixes_applied": len(_workloop_status.get("fix_log", [])),
        },
    }


@router.get("/system/workloop")
async def workloop_status(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Detailed workloop monitor status — failure patterns, findings, auto-fixes applied."""
    try:
        from aether_os.core.workloop_monitor import get_workloop_monitor
        return get_workloop_monitor().get_status()
    except Exception as exc:
        return {"error": str(exc), "running": False}


@router.get("/health/observability")
async def health_observability() -> Dict[str, Any]:
    """
    Observability health — LangSmith status and today's trace count.
    Returns: {langsmith, last_trace_id, traces_today}
    No auth required (public health probe).
    """
    from aether_os.core.telemetry.langsmith_tracer import get_status
    return get_status()


@router.get("/health/sla")
async def health_sla(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    """T4-10: SLA metrics — uptime window, run completion rate, p50/p95 duration.

    Calculates from the last 30 days of run data for the org.
    These numbers feed into SLA credit calculations for enterprise plans.
    """
    import time as _t_sla
    org_id = user["org_id"]
    window_days = 30
    since = _t_sla.time() - window_days * 86400
    try:
        from aether_os.core.db import get_session_factory as _gsf_sla
        from aether_os.core.models import Run as _Run_sla
        from sqlalchemy import select as _sel_sla, func as _func_sla
        async with _gsf_sla()() as _sess:
            q = _sel_sla(_Run_sla).where(
                _Run_sla.org_id == org_id,
                _Run_sla.started_at >= since,
            )
            rows = (await _sess.execute(q)).scalars().all()
    except Exception:
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
            except Exception:
                pass
    durations.sort()

    def percentile(data, pct):
        if not data:
            return None
        idx = max(0, int(len(data) * pct / 100) - 1)
        return round(data[idx], 1)

    completion_rate = round(completed / max(total, 1), 4)
    return {
        "window_days": window_days,
        "total_runs": total,
        "completed_runs": completed,
        "failed_runs": failed,
        "completion_rate": completion_rate,
        "uptime_sla_met": completion_rate >= 0.995,  # 99.5% target
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
    """
    Aggregate cost summary for the current org.
    Backed by TokenBudgetManager (token_budget.db) + LLMCache stats.
    """
    org_id = user["org_id"]
    plan = user.get("plan", "trial")

    # Current month usage from TokenBudgetManager
    try:
        from aether_os.core.llm.budget import get_budget_manager, _PLAN_BUDGETS
        bm = get_budget_manager()
        usage = await bm.get_usage(org_id)
        history = await bm.get_cost_report(org_id, months=3)
        budget_tokens = _PLAN_BUDGETS.get(plan, 500_000)
        budget_used_pct = round(usage["total_tokens"] / max(budget_tokens, 1) * 100, 1)
    except Exception:
        usage = {"input_tokens": 0, "output_tokens": 0, "runs": 0,
                 "estimated_cost_usd": 0.0, "total_tokens": 0,
                 "cache_hits": 0, "cache_misses": 0}
        history = []
        budget_tokens = 500_000
        budget_used_pct = 0.0

    # Cache hit stats
    try:
        from aether_os.core.llm.cache import get_llm_cache
        cache_stats = await get_llm_cache().get_stats()
    except Exception:
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
                <p>₹2,00,000 One-time</p>
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
async def list_feature_flags():
    """Return current platform feature flag states (admin use)."""
    from aether_os.core.feature_flags import flags
    return {"flags": flags.all_flags(), "source": "growthbook+env+defaults"}


@router.post("/system/feature-flags/{flag}")
async def set_feature_flag(flag: str, body: dict = {}):
    """Override a platform feature flag at runtime via env var."""
    import os
    value = body.get("enabled", True)
    key = f"FEATURE_{flag.upper()}"
    os.environ[key] = "true" if value else "false"
    return {"flag": flag, "enabled": value, "env_key": key}
