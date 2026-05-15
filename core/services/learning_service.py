"""
Per-user isolated learning loop.
CRITICAL invariant: every DB query MUST filter by both org_id AND user_id.
Patterns are never shared across org or user boundaries.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_VALID_PATTERN_TYPES = frozenset({
    "naming_convention",
    "architecture_preference",
    "tech_stack",
    "error_pattern",
    "code_style",
    "domain_expertise",
    "deployment_preference",
})


async def get_user_context(
    org_id: str,
    user_id: str,
    session: AsyncSession,
    min_confidence: float = 0.3,
    limit: int = 50,
) -> Dict[str, Any]:
    """Return learned patterns for a user, grouped by type. Used for LLM prompt injection."""
    from aether_os.core.models import UserLearningPattern

    stmt = (
        select(UserLearningPattern)
        .where(
            UserLearningPattern.org_id == org_id,
            UserLearningPattern.user_id == user_id,
            UserLearningPattern.confidence >= min_confidence,
        )
        .order_by(UserLearningPattern.confidence.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    patterns = result.scalars().all()

    grouped: Dict[str, Any] = {}
    for p in patterns:
        grouped.setdefault(p.pattern_type, {})[p.pattern_key] = {
            "value": p.pattern_value,
            "confidence": p.confidence,
            "occurrences": p.occurrence_count,
        }
    return grouped


async def upsert_pattern(
    org_id: str,
    user_id: str,
    pattern_type: str,
    pattern_key: str,
    value: Any,
    run_id: Optional[str],
    session: AsyncSession,
) -> None:
    """Upsert a learned pattern for a user. Confidence grows with repeated observation."""
    if pattern_type not in _VALID_PATTERN_TYPES:
        logger.warning("Unknown pattern_type %r — skipping", pattern_type)
        return

    from aether_os.core.models import UserLearningPattern

    existing = (
        await session.execute(
            select(UserLearningPattern).where(
                UserLearningPattern.org_id == org_id,
                UserLearningPattern.user_id == user_id,
                UserLearningPattern.pattern_type == pattern_type,
                UserLearningPattern.pattern_key == pattern_key,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.occurrence_count += 1
        existing.confidence = min(1.0, existing.confidence + 0.1)
        existing.pattern_value = value if isinstance(value, dict) else {"v": value}
        existing.last_updated_at = datetime.utcnow()
        if run_id:
            try:
                ids = json.loads(existing.source_run_ids or "[]")
            except (json.JSONDecodeError, TypeError):
                ids = []
            if run_id not in ids:
                ids.append(run_id)
            existing.source_run_ids = json.dumps(ids[-20:])  # keep last 20
    else:
        session.add(
            UserLearningPattern(
                org_id=org_id,
                user_id=user_id,
                pattern_type=pattern_type,
                pattern_key=pattern_key,
                pattern_value=value if isinstance(value, dict) else {"v": value},
                confidence=0.5,
                source_run_ids=json.dumps([run_id]) if run_id else "[]",
            )
        )
    await session.commit()


async def extract_patterns_from_run(
    run_id: str,
    org_id: str,
    user_id: str,
    session: AsyncSession,
) -> None:
    """
    Extract and persist user-specific patterns from a completed run.
    Called from factory_pipeline after each phase completion.
    """
    from aether_os.core.models import Run

    run = await session.get(Run, run_id)
    if not run:
        return

    if run.tech_stack:
        await upsert_pattern(
            org_id, user_id, "tech_stack", "preferred_stack",
            {"stack": run.tech_stack}, run_id, session,
        )

    if run.status == "complete":
        await upsert_pattern(
            org_id, user_id, "deployment_preference", "last_successful_deploy",
            {"status": "complete", "live_url": run.live_url}, run_id, session,
        )


async def get_pending_clarifications(
    org_id: str,
    user_id: str,
    session: AsyncSession,
) -> List[Dict[str, Any]]:
    """Return unanswered, non-expired clarification questions for the user."""
    from aether_os.core.models import LearningClarificationPending

    stmt = select(LearningClarificationPending).where(
        LearningClarificationPending.org_id == org_id,
        LearningClarificationPending.user_id == user_id,
        LearningClarificationPending.answered_at.is_(None),
        LearningClarificationPending.expires_at > datetime.utcnow(),
    ).order_by(LearningClarificationPending.created_at.asc())
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "question": r.question,
            "question_type": r.question_type,
            "run_id": r.run_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def answer_clarification(
    clarification_id: str,
    org_id: str,
    user_id: str,
    answer: Any,
    session: AsyncSession,
) -> bool:
    """Mark a clarification as answered. Returns False if not found or already answered."""
    from aether_os.core.models import LearningClarificationPending

    row = (
        await session.execute(
            select(LearningClarificationPending).where(
                LearningClarificationPending.id == clarification_id,
                LearningClarificationPending.org_id == org_id,
                LearningClarificationPending.user_id == user_id,
                LearningClarificationPending.answered_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if not row:
        return False

    row.answered_at = datetime.utcnow()
    row.answer = answer if isinstance(answer, dict) else {"text": str(answer)}
    await session.commit()
    return True


async def store_clarification(
    org_id: str,
    user_id: str,
    run_id: str,
    question: str,
    question_type: str,
    context: Optional[Dict[str, Any]],
    session: AsyncSession,
) -> Optional[str]:
    """
    Store a new clarification question. Returns the question ID, or None if the
    user already has 3 pending questions (to avoid overwhelming them).
    """
    from aether_os.core.models import LearningClarificationPending

    pending_count = (
        await session.execute(
            select(func.count(LearningClarificationPending.id)).where(
                LearningClarificationPending.org_id == org_id,
                LearningClarificationPending.user_id == user_id,
                LearningClarificationPending.answered_at.is_(None),
                LearningClarificationPending.expires_at > datetime.utcnow(),
            )
        )
    ).scalar_one()

    if pending_count >= 3:
        return None

    row = LearningClarificationPending(
        org_id=org_id,
        user_id=user_id,
        run_id=run_id,
        question=question,
        question_type=question_type,
        context=context,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row.id
