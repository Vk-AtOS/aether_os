"""
AetherOS — Prometheus Metrics Router
GET /metrics  — Prometheus metrics endpoint (key-protected when METRICS_API_KEY is set)
"""
from __future__ import annotations

import logging
import hmac
import os
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import Response

logger = logging.getLogger(__name__)
router = APIRouter(tags=["metrics"])

_metrics_api_key = os.environ.get("METRICS_API_KEY", "")
if not _metrics_api_key:
    # Always protect /metrics — generate an ephemeral key so the endpoint is
    # never public even when the operator forgets to set METRICS_API_KEY.
    _metrics_api_key = secrets.token_urlsafe(32)
    # The key itself is never logged — anyone with log access could scrape /metrics.
    logger.warning("METRICS_API_KEY not set — /metrics is locked behind an ephemeral key; set METRICS_API_KEY to scrape")


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint(request: Request):
    """Prometheus metrics — protected by X-Metrics-Key header when METRICS_API_KEY is set."""
    provided = request.headers.get("X-Metrics-Key", "")
    if not hmac.compare_digest(provided.encode(), _metrics_api_key.encode()):
        return Response(status_code=401, content="Unauthorized")
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except ImportError:
        return Response(status_code=503, content="Prometheus client not installed")
    except Exception as exc:
        logger.warning("Failed to generate Prometheus metrics: %s", exc)
        return Response(status_code=500, content="Metrics unavailable")
