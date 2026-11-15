"""
AetherOS — Health & Landing Router
GET /health          — health check (app-level)
GET /healthz         — liveness (no dependencies)
GET /readyz          — readiness (Postgres, Redis; names degraded components)
GET /api/health      — health check (api prefix)
GET /                — root landing page (public/index.html or redirect)
GET /favicon.ico     — favicon
GET /favicon.svg     — favicon
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

# Path to public/ directory relative to this file:
# __file__ = .../gateway/routers/health_router.py
# public/  = .../public/
_PUBLIC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../public")
)


@router.get("/health")
@router.get("/api/health")
async def health() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "timestamp": time.time(),
        "service": "AetherOS API",
        "version": "1.0.0",
    }


@router.get("/healthz")
async def healthz() -> Dict[str, str]:
    """Liveness: the process is up and its event loop answers. Touches no dependency, so a Postgres or Redis outage
    never makes an orchestrator kill a container that is only waiting for them."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    """Readiness: 200 when this instance can serve traffic, 503 when it cannot (load balancers stop routing to it).
    Names the degraded components but nothing else; details are admin-only at /system/components."""
    from aether_os.core.resilience.health import snapshot
    snap = await snapshot()
    body = {"ready": snap["ready"], "degraded": snap["degraded"]}
    return JSONResponse(body, status_code=200 if snap["ready"] else 503)


@router.get("/health/zero-trust")
@router.get("/api/health/zero-trust")
async def health_zero_trust() -> Dict[str, Any]:
    """Zero-trust subsystem health check.

    Issues and immediately verifies a probe ticket to confirm that
    AETHER_ONE_ZT_SECRET is set and HMAC signing is operational.
    """
    import os
    secret_set = bool(os.environ.get("AETHER_ONE_ZT_SECRET", ""))
    if not secret_set:
        return {
            "status": "degraded",
            "zero_trust": False,
            "reason": "AETHER_ONE_ZT_SECRET is not set",
            "timestamp": time.time(),
        }
    try:
        from aether_os.core.identity.zero_trust import issue_ticket, verify_ticket
        _probe_project = "__zt_health_probe__"
        _probe_resource = "__probe__"
        _probe_action = "health_check"
        ticket = issue_ticket(_probe_project, _probe_resource, _probe_action)
        verify_ticket(ticket, _probe_project, _probe_resource, _probe_action)
        return {
            "status": "ok",
            "zero_trust": True,
            "timestamp": time.time(),
        }
    except Exception as exc:
        logger.warning("Zero-trust health probe failed: %s", exc)
        return {
            "status": "degraded",
            "zero_trust": False,
            "reason": str(exc),
            "timestamp": time.time(),
        }


@router.get("/")
async def root_landing():
    """Serve the public landing page."""
    _landing = os.path.join(_PUBLIC_DIR, "index.html")
    if os.path.isfile(_landing):
        return FileResponse(_landing, media_type="text/html")
    return RedirectResponse(url="/dashboard/")


@router.get("/favicon.ico", include_in_schema=False)
@router.get("/favicon.svg", include_in_schema=False)
async def favicon():
    """Serve the AetherOS favicon."""
    _svg = os.path.join(_PUBLIC_DIR, "favicon.svg")
    if os.path.isfile(_svg):
        return FileResponse(_svg, media_type="image/svg+xml")
    return Response(status_code=204)
