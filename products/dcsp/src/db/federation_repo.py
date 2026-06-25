"""
CRUD operations for the FederationPattern model.

Replaces the in-memory _PATTERNS dict in registry_server.py so that
anonymized repair patterns persist across process restarts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.models import FederationPattern

logger = logging.getLogger(__name__)


def _compute_confidence(success_count: int) -> float:
    """Replicate the registry_server confidence formula so behaviour is identical."""
    if success_count == 0:
        return 0.5
    return min(0.5 + success_count * 0.05, 0.99)


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def upsert_pattern(
    session: Session,
    fingerprint: str,
    error_type: str,
    language: str,
    patch_template: str,
    log_snippet: str = "",
) -> tuple[FederationPattern, bool]:
    """Insert a new pattern or increment success_count if it already exists.

    Returns (pattern, was_updated).
    """
    existing = (
        session.query(FederationPattern)
        .filter(FederationPattern.fingerprint == fingerprint)
        .first()
    )

    if existing:
        existing.success_count += 1
        existing.confidence = _compute_confidence(existing.success_count)
        try:
            session.commit()
            session.refresh(existing)
        except Exception as e:
            session.rollback()
            logger.warning("federation_repo: upsert commit failed: %s", e, exc_info=True)
            raise
        return existing, True

    pattern = FederationPattern(
        id=str(uuid.uuid4()),
        fingerprint=fingerprint,
        error_type=error_type,
        language=language,
        patch_template=patch_template,
        log_snippet=log_snippet,
        success_count=1,
        confidence=0.55,
        source_hash=str(uuid.uuid4())[:8],
        submitted_at=datetime.utcnow(),
    )
    session.add(pattern)
    try:
        session.commit()
        session.refresh(pattern)
    except Exception as e:
        session.rollback()
        logger.warning("federation_repo: insert commit failed: %s", e, exc_info=True)
        raise
    return pattern, False


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def list_patterns(
    session: Session,
    error_type: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 20,
) -> list[FederationPattern]:
    """Return patterns sorted by confidence descending, optionally filtered."""
    q = session.query(FederationPattern)
    if error_type:
        q = q.filter(FederationPattern.error_type == error_type)
    if language:
        q = q.filter(FederationPattern.language == language)
    return q.order_by(FederationPattern.confidence.desc()).limit(limit).all()


def get_pattern(session: Session, pattern_id: str) -> Optional[FederationPattern]:
    """Fetch a single pattern by primary key."""
    return session.query(FederationPattern).filter(FederationPattern.id == pattern_id).first()


def count_patterns(session: Session) -> int:
    """Return the total number of stored patterns."""
    return session.query(FederationPattern).count()


def get_stats(session: Session) -> dict:
    """Return aggregate statistics (languages, error_types, avg_confidence)."""
    patterns = session.query(FederationPattern).all()
    total = len(patterns)

    languages: dict[str, int] = {}
    error_types: dict[str, int] = {}
    conf_sum = 0.0

    for p in patterns:
        languages[p.language] = languages.get(p.language, 0) + 1
        error_types[p.error_type] = error_types.get(p.error_type, 0) + 1
        conf_sum += p.confidence

    return {
        "total_patterns": total,
        "languages": languages,
        "error_types": error_types,
        "avg_confidence": conf_sum / total if total > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Delete operations
# ---------------------------------------------------------------------------

def delete_pattern(session: Session, pattern_id: str) -> bool:
    """Delete a pattern by ID. Returns True if deleted, False if not found."""
    pattern = get_pattern(session, pattern_id)
    if pattern is None:
        return False
    try:
        session.delete(pattern)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.warning("federation_repo: delete failed: %s", e, exc_info=True)
        raise
    return True
