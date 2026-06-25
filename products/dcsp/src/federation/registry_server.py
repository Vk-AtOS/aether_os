"""
DCSP Federation Registry — FastAPI sub-application.

Patterns are now persisted in PostgreSQL via FederationPattern / federation_repo
instead of an in-memory dict, so data survives restarts.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

from src.database import SessionLocal
from src.db.federation_repo import (
    upsert_pattern,
    list_patterns,
    get_pattern,
    delete_pattern,
    get_stats,
    count_patterns,
)

logger = logging.getLogger(__name__)

_REGISTRY_API_KEY = os.getenv("REGISTRY_SERVER_API_KEY", "")

registry_app = FastAPI(
    title="DCSP Federation Registry",
    description=(
        "Central registry for sharing "
        "anonymized repair patterns"
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class PatternSubmit(BaseModel):
    fingerprint: str
    error_type: str
    language: str
    patch_template: str
    log_snippet: str = ""


class PatternResponse(BaseModel):
    id: str
    fingerprint: str
    error_type: str
    language: str
    patch_template: str
    success_count: int
    confidence: float
    submitted_at: str
    source_hash: str = ""


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _check_api_key(x_api_key: Optional[str]) -> bool:
    """Return True if the API key is valid (or if no key is required)."""
    if not _REGISTRY_API_KEY:
        return True  # open registry
    return x_api_key == _REGISTRY_API_KEY


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@registry_app.get("/health")
async def health():
    session = SessionLocal()
    try:
        total = count_patterns(session)
    except Exception as e:
        logger.warning("federation health check DB error: %s", e, exc_info=True)
        total = -1
    finally:
        session.close()
    return {"status": "ok", "patterns": total}


@registry_app.post("/api/patterns", status_code=201)
async def submit_pattern(
    body: PatternSubmit,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Submit an anonymized repair pattern.

    If the fingerprint already exists, its success_count is incremented.
    """
    if not _check_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    session = SessionLocal()
    try:
        pattern, was_updated = upsert_pattern(
            session,
            fingerprint=body.fingerprint,
            error_type=body.error_type,
            language=body.language,
            patch_template=body.patch_template,
            log_snippet=body.log_snippet,
        )
        return {"id": pattern.id, "updated": was_updated}
    except Exception as e:
        logger.warning("submit_pattern failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error storing pattern")
    finally:
        session.close()


@registry_app.get("/api/patterns")
async def list_patterns_endpoint(
    error_type: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 20,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """List shared patterns, optionally filtered by error_type or language."""
    if not _check_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    session = SessionLocal()
    try:
        patterns = list_patterns(session, error_type=error_type, language=language, limit=limit)
        return {
            "patterns": [
                {
                    "id": p.id,
                    "fingerprint": p.fingerprint,
                    "error_type": p.error_type,
                    "language": p.language,
                    "patch_template": p.patch_template,
                    "success_count": p.success_count,
                    "confidence": p.confidence,
                    "submitted_at": p.submitted_at.isoformat() if p.submitted_at else "",
                    "source_hash": p.source_hash or "",
                }
                for p in patterns
            ],
            "total": len(patterns),
        }
    except Exception as e:
        logger.warning("list_patterns failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error listing patterns")
    finally:
        session.close()


@registry_app.get("/api/patterns/{pattern_id}")
async def get_pattern_endpoint(
    pattern_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Get a specific pattern by ID."""
    if not _check_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    session = SessionLocal()
    try:
        pattern = get_pattern(session, pattern_id)
    except Exception as e:
        logger.warning("get_pattern failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error fetching pattern")
    finally:
        session.close()

    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found")

    return {
        "id": pattern.id,
        "fingerprint": pattern.fingerprint,
        "error_type": pattern.error_type,
        "language": pattern.language,
        "patch_template": pattern.patch_template,
        "success_count": pattern.success_count,
        "confidence": pattern.confidence,
        "submitted_at": pattern.submitted_at.isoformat() if pattern.submitted_at else "",
        "source_hash": pattern.source_hash or "",
    }


@registry_app.delete("/api/patterns/{pattern_id}", status_code=204)
async def delete_pattern_endpoint(
    pattern_id: str,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Delete a pattern (admin only)."""
    if not _check_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    session = SessionLocal()
    try:
        found = delete_pattern(session, pattern_id)
    except Exception as e:
        logger.warning("delete_pattern failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error deleting pattern")
    finally:
        session.close()

    if not found:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return None


@registry_app.get("/api/stats")
async def registry_stats(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Registry aggregate statistics."""
    if not _check_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    session = SessionLocal()
    try:
        return get_stats(session)
    except Exception as e:
        logger.warning("registry_stats failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error fetching stats")
    finally:
        session.close()
