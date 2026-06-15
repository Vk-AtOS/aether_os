"""
AetherOS — Global Pattern Learning Service.

Records cross-org aggregate patterns after each successful build.
Keyed on (domain, pattern_type); updated with rolling averages so
the system genuinely learns which domains/patterns produce quality output.

PRIVACY NOTE: GlobalPattern stores only aggregate statistics (counts, averages).
No user-specific data, raw prompts, or org IDs are stored here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def record_global_pattern(
    run_id: str,
    domain: str,
    quality_score_total: float,
    quality_details: Dict[str, Any],
    session: Any,  # AsyncSession
) -> None:
    """
    Upsert GlobalPattern rows after a completed build.

    Called from the run-completion handler with the quality score so the
    system can track which (domain, pattern_type) combinations produce
    high-quality output over time.

    Parameters
    ----------
    run_id:
        The completed run's ID (used only for logging).
    domain:
        Project domain (e.g. "healthcare", "fintech", "general").
    quality_score_total:
        Composite quality score 0-100 from QualityScore.total.
    quality_details:
        QualityScore.details dict — used to derive pattern types.
    session:
        Active SQLAlchemy AsyncSession.
    """
    from aether_os.core.models import GlobalPattern

    # Derive pattern types from quality details.
    # Each completed build contributes to one or more pattern types.
    patterns_to_record = _derive_pattern_types(quality_details)

    for pattern_type in patterns_to_record:
        try:
            from sqlalchemy import select
            stmt = select(GlobalPattern).where(
                GlobalPattern.domain == domain,
                GlobalPattern.pattern_type == pattern_type,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Rolling average — keeps the score current without unbounded growth
                n = existing.usage_count
                existing.avg_quality_score = (
                    (existing.avg_quality_score * n + quality_score_total) / (n + 1)
                )
                existing.usage_count = n + 1
                # Adjust success_rate by small increments so it converges toward true rate
                if quality_score_total > 60:
                    existing.success_rate = min(1.0, existing.success_rate + 0.05)
                else:
                    existing.success_rate = max(0.0, existing.success_rate - 0.05)
                existing.last_updated = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                pattern_name = f"{domain}_{pattern_type}"
                initial_success = 1.0 if quality_score_total > 60 else 0.5
                session.add(
                    GlobalPattern(
                        domain=domain,
                        pattern_name=pattern_name,
                        pattern_type=pattern_type,
                        success_rate=initial_success,
                        usage_count=1,
                        avg_quality_score=float(quality_score_total),
                        last_updated=datetime.now(timezone.utc).replace(tzinfo=None),
                    )
                )

        except Exception as exc:
            # Non-fatal: pattern recording should never break the pipeline
            logger.warning(
                "GlobalPattern upsert failed run=%s domain=%s type=%s: %s",
                run_id, domain, pattern_type, exc,
            )

    try:
        await session.commit()
        logger.info(
            "GlobalPattern updated: run=%s domain=%s types=%s score=%.1f",
            run_id, domain, patterns_to_record, quality_score_total,
        )
    except Exception as exc:
        logger.warning("GlobalPattern commit failed run=%s: %s", run_id, exc)


def _derive_pattern_types(quality_details: Dict[str, Any]) -> list:
    """
    Derive a list of pattern type strings from a QualityScore.details dict.

    Always returns at least ["crud"] as a catch-all type.
    Additional types are inferred from route counts and file presence.
    """
    types = []

    route_count = quality_details.get("routes", 0) or 0
    write_routes = quality_details.get("total_write_routes", 0) or 0
    auth_total = quality_details.get("auth_total", 0) or 0

    if write_routes > 0:
        types.append("crud")
    if auth_total > 0:
        types.append("auth")
    if quality_details.get("has_frontend"):
        types.append("fullstack")
    if quality_details.get("has_compliance"):
        types.append("compliance")
    if quality_details.get("has_docker"):
        types.append("containerised")

    # Ensure at least one type is always recorded
    if not types:
        types.append("crud")

    return types
