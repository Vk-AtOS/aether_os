"""
AetherOS — GoldenRetriever
Stores build feedback, promotes high-rated builds to golden examples,
and retrieves few-shot context for LLM prompts.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Threshold: average rating >= this → eligible for golden promotion
GOLDEN_RATING_THRESHOLD = 4.0
# Max golden examples injected into a single LLM prompt
MAX_GOLDEN_EXAMPLES = 2


async def record_feedback(
    run_id: str,
    org_id: str,
    user_id: Optional[str],
    rating: int,
    tags: Optional[List[str]],
    comment: Optional[str],
    session,
) -> Dict[str, Any]:
    """Persist a BuildFeedback row and trigger golden promotion check."""
    from aether_os.core.models import BuildFeedback, Run, GoldenBuild
    from sqlalchemy import select, func
    from sqlalchemy.exc import IntegrityError

    rating = max(1, min(5, int(rating)))

    # One rating per user per run (uq_build_feedback_run_user): a second submit replaces the first
    # instead of counting twice or failing.
    fb = None
    if user_id:
        fb = (await session.execute(
            select(BuildFeedback).where(BuildFeedback.run_id == run_id, BuildFeedback.user_id == user_id)
        )).scalar_one_or_none()
    if fb is not None:
        fb.rating, fb.tags, fb.comment = rating, tags or [], comment
    else:
        fb = BuildFeedback(
            id=str(uuid.uuid4()),
            run_id=run_id,
            org_id=org_id,
            user_id=user_id,
            rating=rating,
            tags=tags or [],
            comment=comment,
        )
        session.add(fb)
    await session.flush()

    # Compute average rating for this run
    avg_q = await session.execute(
        select(func.avg(BuildFeedback.rating)).where(BuildFeedback.run_id == run_id, BuildFeedback.org_id == org_id)
    )
    avg_rating: float = float(avg_q.scalar() or rating)

    # Auto-promote if avg >= threshold and not already golden
    if avg_rating >= GOLDEN_RATING_THRESHOLD:
        existing = await session.execute(
            select(GoldenBuild).where(GoldenBuild.run_id == run_id)
        )
        if existing.scalar_one_or_none() is None:
            run_q = await session.execute(select(Run).where(Run.id == run_id, Run.org_id == org_id))
            run = run_q.scalar_one_or_none()
            if run:
                golden = await _build_golden_record(run, avg_rating, session)
                if golden:
                    try:
                        async with session.begin_nested():  # savepoint: a lost race must not undo the feedback row
                            session.add(golden)
                        logger.info("golden_retriever: promoted run %s (avg_rating=%.1f) to golden", run_id, avg_rating)
                    except IntegrityError:
                        logger.info("golden_retriever: run %s was promoted concurrently", run_id)

    await session.commit()
    return {"id": fb.id, "rating": rating, "avg_rating": avg_rating}


async def _build_golden_record(run, avg_rating: float, session) -> Optional[Any]:
    """Build a GoldenBuild ORM instance from a completed Run."""
    from aether_os.core.models import GoldenBuild, Snapshot

    domain = getattr(run, "domain", None) or "general"
    project_name = getattr(run, "project_name", None) or "Unnamed"
    prompt_summary = (getattr(run, "requirement", None) or getattr(run, "raw_input", None) or "")[:500]
    quality_score = float(getattr(run, "quality_score", 0) or 0)

    # Pull model sample from snapshots
    p04_sample = p05_sample = None
    try:
        from sqlalchemy import select
        snaps_q = await session.execute(
            select(Snapshot).where(Snapshot.run_id == run.id)
        )
        snaps = snaps_q.scalars().all()
        for snap in snaps:
            fp = str(snap.file_path or "")
            if "models.py" in fp and not p04_sample and snap.content:
                p04_sample = snap.content[:3000]
            if "Dashboard.tsx" in fp and not p05_sample and snap.content:
                p05_sample = snap.content[:3000]
    except Exception as exc:
        logger.debug("golden_retriever: snapshot fetch error: %s", exc)

    # Domain IR summary from pipeline output
    domain_ir_summary = None
    try:
        phases = getattr(run, "phases", None) or {}
        if isinstance(phases, dict):
            p02_out = phases.get("p02_architect", {})
            entities = (p02_out or {}).get("entities", [])
            if entities:
                domain_ir_summary = {
                    "entity_names": [e.get("name", "") for e in entities[:10]],
                    "entity_count": len(entities),
                }
    except Exception as exc:
        logger.debug("golden_retriever: domain IR summary extraction failed: %s", exc)

    return GoldenBuild(
        id=str(uuid.uuid4()),
        run_id=run.id,
        org_id=run.org_id or "",
        domain=domain,
        project_name=project_name,
        prompt_summary=prompt_summary,
        quality_score=quality_score,
        user_rating=avg_rating,
        p04_sample=p04_sample,
        p05_sample=p05_sample,
        entity_count=len((domain_ir_summary or {}).get("entity_names", [])),
        domain_ir_summary=domain_ir_summary,
        is_active=True,
    )


async def get_golden_examples(
    domain: str, limit: int = MAX_GOLDEN_EXAMPLES, org_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve active golden builds for a domain, used as few-shot LLM context.

    Tenant data: only the caller's own organisation's builds, plus platform-owned
    ones (org_id == ""). Without an org_id only platform-owned builds are returned,
    so one customer's generated code can never be put into another's prompt.
    """
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import GoldenBuild
        from sqlalchemy import select, or_

        sf = get_session_factory()
        async with sf() as session:
            q = await session.execute(
                select(GoldenBuild)
                .where(GoldenBuild.is_active == True)
                .where(GoldenBuild.org_id.in_(("", org_id) if org_id else ("",)))
                .where(or_(GoldenBuild.domain == domain, GoldenBuild.domain == "general"))
                .order_by(GoldenBuild.user_rating.desc().nullslast(), GoldenBuild.quality_score.desc().nullslast())
                .limit(limit)
            )
            rows = q.scalars().all()
            return [
                {
                    "project_name": r.project_name,
                    "domain": r.domain,
                    "prompt_summary": r.prompt_summary,
                    "quality_score": r.quality_score,
                    "user_rating": r.user_rating,
                    "p04_sample": r.p04_sample,
                    "p05_sample": r.p05_sample,
                    "entity_count": r.entity_count,
                    "domain_ir_summary": r.domain_ir_summary,
                }
                for r in rows
            ]
    except Exception as exc:
        logger.debug("golden_retriever: get_golden_examples error: %s", exc)
        return []


def format_golden_hint_p04(examples: List[Dict]) -> str:
    """Format golden examples as a few-shot hint for p04 model/schema generation."""
    if not examples:
        return ""
    parts = ["\n=== GOLDEN EXAMPLES (high-rated past builds — use as style reference) ==="]
    for ex in examples:
        parts.append(f"\n--- Example: {ex['project_name']} ({ex['domain']}) ---")
        if ex.get("prompt_summary"):
            parts.append(f"Original request: {ex['prompt_summary'][:200]}")
        if ex.get("p04_sample"):
            parts.append("models.py excerpt:\n" + ex["p04_sample"][:1500])
    parts.append("=== END GOLDEN EXAMPLES ===\n")
    return "\n".join(parts)


def format_golden_hint_p05(examples: List[Dict]) -> str:
    """Format golden examples as a few-shot hint for p05 frontend generation.

    Only injects examples that have a domain-specific feel (not generic white/gray defaults).
    The hint explicitly instructs the LLM to adapt — not copy — the style.
    """
    if not examples:
        return ""
    # Filter out examples that look like the generic default blue template
    _generic_signals = ("bg-white", "text-gray-900", "border-gray-100", "bg-gray-50")
    filtered = []
    for ex in examples:
        sample = ex.get("p05_sample") or ""
        # Skip if >70% of colour classes are generic grey/white
        generic_hits = sum(1 for s in _generic_signals if s in sample)
        if generic_hits < 3:  # has distinct domain colours
            filtered.append(ex)

    if not filtered:
        return ""

    parts = [
        "\n=== STYLE REFERENCE (high-rated builds — ADAPT the domain colour scheme, do NOT copy code) ===",
        "Important: these are style references only. Use the domain colour palette from the requirements above.",
    ]
    for ex in filtered:
        parts.append(f"\n--- Reference: {ex['project_name']} ({ex['domain']}) ---")
        if ex.get("p05_sample"):
            # Only show the colour-related lines to avoid copying structure
            colour_lines = [
                ln for ln in ex["p05_sample"].splitlines()
                if any(kw in ln for kw in ("className", "bg-", "text-", "border-", "from-", "to-", "via-"))
            ][:30]
            if colour_lines:
                parts.append("Colour classes used:\n" + "\n".join(colour_lines))
    parts.append("=== END STYLE REFERENCE ===\n")
    return "\n".join(parts)


async def get_stats(org_id: str) -> Dict[str, Any]:
    """Return self-improvement system statistics."""
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import BuildFeedback, GoldenBuild
        from sqlalchemy import select, func

        sf = get_session_factory()
        async with sf() as session:
            fb_count = (await session.execute(select(func.count()).select_from(BuildFeedback).where(BuildFeedback.org_id == org_id))).scalar() or 0
            golden_count = (await session.execute(
                select(func.count()).select_from(GoldenBuild)
                .where(GoldenBuild.is_active == True, GoldenBuild.org_id == org_id)
            )).scalar() or 0
            avg_rating = (await session.execute(select(func.avg(BuildFeedback.rating)).where(BuildFeedback.org_id == org_id))).scalar()
            domain_stats_q = await session.execute(
                select(GoldenBuild.domain, func.count(), func.avg(GoldenBuild.user_rating))
                .where(GoldenBuild.is_active == True, GoldenBuild.org_id == org_id)
                .group_by(GoldenBuild.domain)
            )
            domain_stats = [
                {"domain": row[0], "count": row[1], "avg_rating": round(float(row[2] or 0), 2)}
                for row in domain_stats_q.all()
            ]
        return {
            "total_feedback": fb_count,
            "golden_builds": golden_count,
            "avg_rating": round(float(avg_rating or 0), 2),
            "domain_stats": domain_stats,
        }
    except Exception as exc:
        logger.debug("golden_retriever: get_stats error: %s", exc)
        return {"total_feedback": 0, "golden_builds": 0, "avg_rating": 0.0, "domain_stats": []}


async def get_golden_builds_list(org_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """List golden builds for the UI."""
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import GoldenBuild
        from sqlalchemy import select

        sf = get_session_factory()
        async with sf() as session:
            q = await session.execute(
                select(GoldenBuild)
                .where(GoldenBuild.is_active == True, GoldenBuild.org_id == org_id)
                .order_by(GoldenBuild.user_rating.desc().nullslast(), GoldenBuild.created_at.desc())
                .limit(limit)
            )
            rows = q.scalars().all()
            return [
                {
                    "id": r.id,
                    "run_id": r.run_id,
                    "domain": r.domain,
                    "project_name": r.project_name,
                    "prompt_summary": r.prompt_summary,
                    "quality_score": r.quality_score,
                    "user_rating": r.user_rating,
                    "entity_count": r.entity_count,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
    except Exception as exc:
        logger.debug("golden_retriever: get_golden_builds_list error: %s", exc)
        return []
