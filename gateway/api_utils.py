"""
AetherOS — API Gateway Utilities
==================================
Helper functions extracted from gateway/api.py to keep it under 600 lines.

Exported:
    _init_sentry()       — initialise Sentry error tracking from env
    _get_cors_origins()  — read CORS allowed origins from env
    _json_safe()         — recursively make an object JSON-serialisable
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


# ── Sentry initialisation ──────────────────────────────────────────────────────

def _init_sentry() -> None:
    """C10: Sentry error tracking — reads SENTRY_DSN from env."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        sentry_sdk.init(
            dsn=dsn,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            environment=os.environ.get("ENVIRONMENT", "development"),
            send_default_pii=False,
        )
        logger.info("Sentry error tracking enabled")
    except ImportError:
        logger.warning("sentry-sdk not installed — error tracking disabled")
    except Exception as exc:
        logger.warning("Sentry init failed: %s", exc)


# ── CORS configuration ─────────────────────────────────────────────────────────

def _get_cors_origins() -> list:
    """
    Bug 3 fix: CORS origins come from env var only. Never wildcard in production.
    Default is localhost for development.
    """
    raw = os.environ.get("CORS_ORIGINS", "")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]

    # Default development origins
    return [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://localhost:5173",  # Vite default
    ]


# ── JSON serialisation helper ──────────────────────────────────────────────────

def _json_safe(obj):
    """Recursively convert bytes/dicts/lists to JSON-safe Python types."""
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj
