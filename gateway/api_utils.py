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
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        # the app sends credentials: '*' with credentials makes the browser-facing rule "any site may read
        # a signed-in user's responses" (KAN-69 F21), so refuse to start rather than run that way
        if "*" in origins:
            raise RuntimeError("CORS_ORIGINS must list explicit origins; '*' is not allowed (credentials are enabled)")
        return origins

    # Default development origins
    return [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://localhost:5173",  # Vite default
    ]


# ── Golden example seeder ─────────────────────────────────────────────────────

async def _seed_golden_examples_if_empty() -> None:
    """Seed GoldenBuild table from JSON files on disk if the table is empty.

    Reads core/knowledge_graph/golden_examples/*.json (written by
    scripts/seed_golden_examples.py) and inserts one GoldenBuild row per
    example.  Only runs when the table contains zero rows, so it is safe
    to call on every startup.
    """
    import json as _json
    import uuid as _uuid
    from pathlib import Path as _Path
    from sqlalchemy import select as _select, func as _func
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import GoldenBuild as _GB

    _sf = _gsf()
    async with _sf() as _sess:
        count = await _sess.scalar(_select(_func.count()).select_from(_GB))
        if count and count > 0:
            return  # table already populated

    logger.info("GoldenBuild table empty — seeding golden examples from JSON files")
    _examples_dir = _Path(__file__).parent.parent / "core" / "knowledge_graph" / "golden_examples"
    if not _examples_dir.exists():
        logger.warning("golden examples dir not found at %s — skipping seed", _examples_dir)
        return

    _rows_added = 0
    async with _sf() as _sess:
        for _jf in sorted(_examples_dir.glob("*.json")):
            try:
                _data = _json.loads(_jf.read_text())
                _domain = _data.get("domain", _jf.stem)
                for _ex in _data.get("examples", []):
                    _out = _ex.get("output", {})
                    _gb = _GB(
                        id=str(_uuid.uuid4()),
                        run_id=f"seed-{_ex.get('id', _uuid.uuid4())}",
                        org_id="system",
                        domain=_out.get("domain") or _domain,
                        project_name=_ex.get("id", "golden_example"),
                        prompt_summary=(_ex.get("input") or "")[:500],
                        quality_score=float(_ex.get("quality_score", 1.0)) * 100,
                        domain_ir_summary=_out,
                        is_active=True,
                    )
                    _sess.add(_gb)
                    _rows_added += 1
            except Exception as _exc:
                logger.warning("golden seed: skipping %s: %s", _jf.name, _exc)
        await _sess.commit()
    logger.info("Golden examples seeded successfully: %d rows from %s", _rows_added, _examples_dir)


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
