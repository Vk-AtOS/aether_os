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

import json
import logging
import os
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from aether_os.core.db import get_session_factory
from aether_os.core.models import GoldenBuild

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

# Build examples only: bug_to_fix and entity_to_sqlalchemy files are read straight from JSON by
# core/llm/retrieval_ranker.py and have a different shape (dict input, str output).
_GOLDEN_SEED_SKIP_TYPES = frozenset({"bug_to_fix", "entity_to_sqlalchemy"})
_GOLDEN_SEED_NS = uuid.UUID("6f0c1a52-6c1e-4f3b-9a51-1f3f2b7d9e10")


def golden_seed_rows(examples_dir: Path) -> list[dict]:
    """GoldenBuild column values for every build example under examples_dir.

    run_id is a uuid5 of file and example id (or position): 36 characters, fits runs-sized
    String(36) columns, and is the same on every start. Most examples have no id; the old
    "seed-" + uuid4 run id was 41 characters, PostgreSQL refused it and the one shared commit
    rolled back the whole seed (SQLite does not enforce lengths, so tests never saw it).
    """
    rows: list[dict] = []
    for jf in sorted(examples_dir.glob("*.json")):
        try:
            data = json.loads(jf.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("golden seed: skipping %s: %s", jf.name, exc)
            continue
        file_domain = data.get("domain", jf.stem) if isinstance(data, dict) else jf.stem
        examples = data.get("examples", []) if isinstance(data, dict) else []
        for pos, ex in enumerate(examples):
            # Entity records (name/fields, from the sql-create-context corpus) carry no "input": they feed the
            # retrieval ranker, not the few-shot build table.
            if not isinstance(ex, dict) or ex.get("type") in _GOLDEN_SEED_SKIP_TYPES or "input" not in ex:
                continue
            prompt, out = ex.get("input"), ex.get("output")
            if not isinstance(prompt, str) or not isinstance(out, dict):
                logger.warning("golden seed: %s example %d is not a build example, skipped", jf.name, pos)
                continue
            key = f"{jf.stem}:{ex.get('id') or pos}"
            rows.append({
                "run_id": str(uuid.uuid5(_GOLDEN_SEED_NS, key)),
                "org_id": "system",
                "domain": str(out.get("domain") or file_domain)[:50],
                "project_name": str(ex.get("id") or f"{jf.stem}_{pos}")[:255],
                "prompt_summary": prompt[:500],
                "quality_score": float(ex.get("quality_score", 1.0)) * 100,
                "domain_ir_summary": out,
                "is_active": True,
            })
    return rows


async def _seed_golden_examples_if_empty() -> None:
    """Seed the GoldenBuild table from core/knowledge_graph/golden_examples/*.json when it is empty.

    Runs on every startup; does nothing once the table has rows.
    """
    sf = get_session_factory()
    async with sf() as sess:
        count = await sess.scalar(select(func.count()).select_from(GoldenBuild))
        if count:
            return

    examples_dir = Path(__file__).parent.parent / "core" / "knowledge_graph" / "golden_examples"
    if not examples_dir.exists():
        logger.warning("golden examples dir not found at %s - skipping seed", examples_dir)
        return
    rows = golden_seed_rows(examples_dir)
    async with sf() as sess:
        sess.add_all(GoldenBuild(**r) for r in rows)
        try:
            await sess.commit()
        except IntegrityError:
            # Every uvicorn worker runs this at start; the stable run ids make the losers collide on
            # uq_golden_build_run instead of inserting duplicate copies. One worker seeded: that is success.
            await sess.rollback()
            logger.info("Golden examples already seeded by another worker")
            return
    logger.info("Golden examples seeded: %d rows from %s", len(rows), examples_dir)


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
