"""
AetherOS — Health & Landing Router
GET /health          — health check (app-level)
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
from fastapi.responses import FileResponse, RedirectResponse, Response

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
