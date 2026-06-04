"""
AetherOS — Prometheus Metrics Router
GET /metrics  — Prometheus metrics endpoint (key-protected when METRICS_API_KEY is set)
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import Response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["metrics"])

_metrics_api_key = os.environ.get("METRICS_API_KEY", "")


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint(request: Request):
    """Prometheus metrics — protected by X-Metrics-Key header when METRICS_API_KEY is set."""
    if _metrics_api_key:
        provided = request.headers.get("X-Metrics-Key", "")
        if provided != _metrics_api_key:
            return Response(status_code=401, content="Unauthorized")
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except ImportError:
        return Response(status_code=503, content="Prometheus client not installed")
    except Exception as exc:
        logger.warning("Failed to generate Prometheus metrics: %s", exc)
        return Response(status_code=500, content="Metrics unavailable")
