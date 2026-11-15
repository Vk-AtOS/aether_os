"""
AetherOS — System Router
GET /system/metrics
GET /system/health
GET /system/workloop
Observability, SLA, costs, pricing, and feature-flags live in system_info_router.py.
"""
from __future__ import annotations
import logging
import os
from typing import Any, Dict
from fastapi import APIRouter, Depends
from aether_os.gateway.dependencies import get_current_user
from aether_os.core.db import get_engine as _ge
from aether_os.core.db import get_session_factory as _gsf
from aether_os.core.db import get_session_factory as _gsf2
from aether_os.core.db import get_session_factory as _gsf_h
from aether_os.core.llm.client import get_llm_client
from aether_os.core.llm.openrouter_client import select_openrouter_model as _sel_or
from aether_os.core.model_router import get_router as _get_router
from aether_os.core.models import Run as _Run
from aether_os.core.pipeline_state import get_redis as _gr
from aether_os.core.workloop_monitor import get_workloop_monitor
from aether_os.core.workloop_monitor import get_workloop_monitor as _gwm
from sqlalchemy import select as _sel, func as _func
from sqlalchemy import text as _ht
from sqlalchemy import text as _t
import httpx as _httpx
import psutil as _psu
import shutil as _shutil
import shutil as _shutil_sb
import subprocess as _sp
import time as _time
logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])
def _current_user():
    return Depends(get_current_user)
@router.get("/system/metrics")
async def system_metrics() -> Dict[str, Any]:
    """System resource metrics — CPU, memory, disk, Redis, DB, pipeline."""
    result: Dict[str, Any] = {"timestamp": _time.time()}
    # System resources
    try:
        result["cpu_percent"] = _psu.cpu_percent(interval=0.1)
        result["memory_percent"] = _psu.virtual_memory().percent
        result["disk_percent"] = _psu.disk_usage("/").percent
    except Exception as exc:
        logger.debug("system_metrics: psutil unavailable: %s", exc)
        result["cpu_percent"] = None
        result["memory_percent"] = None
        result["disk_percent"] = None
    # DB health
    try:
        async with _gsf()() as _s:
            await _s.execute(_t("SELECT 1"))
        result["db"] = "healthy"
    except Exception as exc:
        logger.debug("system_metrics: DB health check failed: %s", exc)
        result["db"] = "unhealthy"
    # Redis health
    try:
        _r = await _gr()
        if _r:
            await _r.ping()
            result["redis"] = "healthy"
        else:
            result["redis"] = "unavailable"
    except Exception as exc:
        logger.debug("system_metrics: Redis health check failed: %s", exc)
        result["redis"] = "unavailable"
    # Active pipeline runs
    try:
        async with _gsf2()() as _s2:
            active_count = (await _s2.execute(
                _sel(_func.count()).select_from(_Run).where(_Run.status == "running")
            )).scalar_one_or_none() or 0
        result["active_runs"] = active_count
    except Exception as exc:
        logger.debug("system_metrics: active runs count failed: %s", exc)
        result["active_runs"] = None
    return result
@router.get("/system/status")
async def system_status() -> Dict[str, Any]:
    """Minimal liveness probe — called by the frontend on every page load."""
    return {"status": "ok", "service": "aetheros-factory", "version": "1.0"}
@router.get("/system/health")
async def system_health(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """System health check with LLM provider status."""
    anthropic_available = bool(os.environ.get("ANTHROPIC_API_KEY"))
    gemini_available = bool(os.environ.get("GOOGLE_API_KEY"))
    openrouter_available = bool(os.environ.get("OPENROUTER_API_KEY"))
    # Check Ollama with 2-second timeout
    ollama_available = False
    try:
        async with _httpx.AsyncClient(timeout=2.0) as _http:
            resp = await _http.get("http://localhost:11434/api/tags")
            ollama_available = resp.status_code == 200
    except Exception as exc:
        logger.debug("system_health: Ollama check failed: %s", exc)
        ollama_available = False
    any_llm = anthropic_available or gemini_available or ollama_available or openrouter_available
    client = get_llm_client()
    active_provider = client.last_provider or os.environ.get("PRIMARY_LLM", "none")
    routing: dict = {}
    try:
        routing = _get_router().get_status()
    except Exception as exc:
        logger.debug("system_health: model router status unavailable: %s", exc)
    health_status = "healthy"
    message = "All systems operational."
    bedrock_available = bool(
        os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    if bedrock_available:
        _bm_heavy = os.environ.get("BEDROCK_MODEL_HEAVY", "us.anthropic.claude-sonnet-4-6")
        health_status = "healthy"
        message = f"Running on Amazon Bedrock ({_bm_heavy})."
    elif openrouter_available and not anthropic_available and not gemini_available and not ollama_available:
        health_status = "ok"
        message = "Running on OpenRouter (configured)."
    elif ollama_available and not anthropic_available and not gemini_available:
        health_status = "ok"
        message = "Running on local Ollama (configured)."
    elif not any_llm:
        health_status = "warning"
        message = "No LLM providers available. System will fail to process tasks."
    llm_display = active_provider
    if active_provider in ("openrouter", "none") and openrouter_available:
        llm_display = f"openrouter ({_sel_or('code_generation')})"
    elif active_provider == "ollama":
        llm_display = f"ollama ({os.environ.get('OLLAMA_MODEL', 'qwen2.5-coder:7b')})"
    db_status = "unhealthy"
    try:
        async with _gsf_h()() as _sh:
            await _sh.execute(_ht("SELECT 1"))
        db_status = "healthy"
    except Exception as exc:
        logger.debug("system_health: DB check failed: %s", exc)
        health_status = "degraded"
        message = "Database unreachable."
    redis_status = "unavailable"
    try:
        _r = await _gr()
        if _r:
            await _r.ping()
            redis_status = "healthy"
    except Exception as exc:
        logger.debug("system_health: Redis check failed: %s", exc)
    try:
        _disk = _shutil.disk_usage(str(os.path.expanduser("~")))
        _free_pct = _disk.free / _disk.total * 100
        disk_status = "healthy" if _free_pct > 10 else "warning"
    except Exception as exc:
        logger.debug("system_health: disk check failed: %s", exc)
        _free_pct = None
        disk_status = "unknown"
    try:
        _proc = _psu.Process()
        _uptime_secs = int(_time.time() - _proc.create_time())
    except Exception as exc:
        logger.debug("system_health: uptime check failed: %s", exc)
        _uptime_secs = None
    _pool_size = None
    try:
        _eng = _ge()
        _pool_size = getattr(getattr(_eng, "pool", None), "size", lambda: None)()
    except Exception as exc:
        logger.debug("system_health: DB pool size unavailable: %s", exc)
    _sandbox_status = "not_configured"
    _sandbox_engine = "none"
    if _shutil_sb.which("docker"):
        # Docker binary exists — check whether the daemon is reachable
        try:
            _docker_res = _sp.run(["docker", "info"], capture_output=True, timeout=3)
            if _docker_res.returncode == 0:
                _sandbox_status = "ok"
                _sandbox_engine = "docker"
            else:
                # Binary present but daemon not running
                _sandbox_status = "unreachable"
                _sandbox_engine = "docker"
        except Exception as exc:
            logger.debug("system_health: docker check failed: %s", exc)
            _sandbox_status = "unreachable"
            _sandbox_engine = "docker"
    # else: docker binary absent → "not_configured" is correct
    _workloop_status: dict = {}
    try:
        _workloop_status = _gwm().get_status()
    except Exception as exc:
        logger.debug("system_health: workloop monitor unavailable: %s", exc)
    # Map internal routing-mode labels to human-readable strings so customers
    # never see implementation details like "cache" or "fallback" as model names.
    _ROUTING_MODE_LABELS = {
        "cache":    "Cached responses",
        "fallback": "Fallback model",
        "mock":     "Mock (testing)",
        "none":     "",
    }
    _raw_active_model = routing.get("active_model") or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "")
    _active_model_display = _ROUTING_MODE_LABELS.get(_raw_active_model, _raw_active_model)
    return {
        "status": health_status,
        "message": message,
        "llm": "healthy" if any_llm else "unavailable",
        "provider": "healthy" if any_llm else "unavailable",
        "llm_provider": llm_display,
        "active_provider": active_provider,
        "active_model": _active_model_display,
        "anthropic_available": anthropic_available,
        "gemini_available": gemini_available,
        "ollama_available": ollama_available,
        "openrouter_available": openrouter_available,
        "fallback_count_today": routing.get("fallback_count_today", 0),
        "model_availability": routing.get("model_availability", {}),
        "version": "1.0.0",
        "uptime": _uptime_secs,
        "database": db_status,
        "db_pool_size": _pool_size,
        "redis": redis_status,
        "cache": redis_status,
        "memory_store": redis_status,
        "sandbox": _sandbox_status,
        "sandbox_engine": _sandbox_engine,
        "active_sandboxes": 0,
        "network": "healthy",
        "disk_free_pct": round(_free_pct, 1) if _free_pct is not None else None,
        "disk_status": disk_status,
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
        return get_workloop_monitor().get_status()
    except Exception as exc:
        logger.warning("system_router: workloop_status failed: %s", exc)
        return {"error": str(exc), "running": False}