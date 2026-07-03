"""
AetherOS — Intelligence Router
GET  /intelligence/global-insights
POST /intelligence/global-patterns
PUT  /intelligence/global-patterns/{pattern_id}
DELETE /intelligence/global-patterns/{pattern_id}
GET  /intelligence/quality-benchmark
POST /intelligence/arch-governor/review
POST /intelligence/truth-engine/validate
POST /intelligence/conflict-resolver/detect
POST /intelligence/conflict-resolver/resolve
POST /intelligence/tradeoff-engine/analyze
POST /intelligence/improvement-loop/cycle
POST /intelligence/maintenance-engine/scan
GET  /intelligence/maintenance-engine/health/{run_id}
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["intelligence"])


def _current_user():
    return Depends(get_current_user)


@router.get("/intelligence/global-insights")
async def get_global_insights(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    """Authenticated intelligence feed — aggregated from GlobalPattern + completed runs."""
    org_id = user["org_id"]
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import GlobalPattern
        from sqlalchemy import text as _text, select as _sel, func as _func
        session_factory = get_session_factory()
        async with session_factory() as session:
            # ── GlobalPattern rows — real learned data ─────────────────────
            gp_rows = (await session.execute(
                _sel(GlobalPattern)
                .where(GlobalPattern.org_id == org_id)
                .order_by(GlobalPattern.usage_count.desc())
                .limit(50)
            )).scalars().all()

            patterns = [
                {
                    "domain": gp.domain,
                    "pattern_name": gp.pattern_name,
                    "pattern_type": gp.pattern_type,
                    "success_rate": round(gp.success_rate, 3),
                    "avg_quality_score": round(gp.avg_quality_score, 1),
                    "usage_count": gp.usage_count,
                    "last_updated": gp.last_updated.isoformat() if gp.last_updated else None,
                }
                for gp in gp_rows
            ]

            # ── Top domains by success_rate from GlobalPattern ─────────────
            top_patterns = sorted(
                [p for p in patterns if p["usage_count"] >= 2],
                key=lambda x: (-x["success_rate"], -x["avg_quality_score"]),
            )[:5]

            # ── Domain distribution from completed runs (fallback/supplement) ─
            try:
                domain_rows = await session.execute(
                    _text(
                        "SELECT domain, COUNT(*) as count FROM runs "
                        "WHERE status='completed' AND domain IS NOT NULL "
                        "GROUP BY domain ORDER BY count DESC LIMIT 20"
                    )
                )
                stats = [{"domain": r[0], "count": r[1]} for r in domain_rows]
            except Exception as e:
                logger.warning("intelligence_router: failed to query domain stats: %s", e)
                stats = []

        return {
            "stats": stats,
            "top_tech_stacks": top_patterns,
            "global_patterns": patterns,
            "total_patterns_learned": len(patterns),
        }
    except Exception as exc:
        logger.debug("global-insights failed: %s", exc)
        return {"stats": [], "top_tech_stacks": [], "global_patterns": [], "total_patterns_learned": 0}


@router.get("/intelligence/global-patterns")
async def list_global_patterns(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return all learned GlobalPattern entries for the platform."""
    org_id = user["org_id"]
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import GlobalPattern
    from sqlalchemy import select
    sf = get_session_factory()
    async with sf() as sess:
        rows = (await sess.execute(
            select(GlobalPattern)
            .where(GlobalPattern.org_id == org_id)
            .order_by(GlobalPattern.usage_count.desc())
        )).scalars().all()
    patterns = [
        {
            "id": p.id,
            "domain": p.domain,
            "pattern_name": p.pattern_name,
            "pattern_type": p.pattern_type,
            "success_rate": round(p.success_rate, 3),
            "avg_quality_score": round(p.avg_quality_score, 1),
            "usage_count": p.usage_count,
            "last_updated": p.last_updated.isoformat() if p.last_updated else None,
        }
        for p in rows
    ]
    return {"patterns": patterns, "total": len(patterns)}


@router.post("/intelligence/global-patterns", status_code=201)
async def create_global_pattern(
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Admin: create a GlobalPattern override to manually tune learned behaviors."""
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import GlobalPattern
    sf = get_session_factory()
    async with sf() as sess:
        p = GlobalPattern(
            org_id=user["org_id"],
            domain=body.get("domain", "general"),
            pattern_name=body.get("pattern_name", ""),
            pattern_type=body.get("pattern_type", "manual"),
            success_rate=float(body.get("success_rate", 1.0)),
            usage_count=int(body.get("usage_count", 1)),
            avg_quality_score=float(body.get("avg_quality_score", 0.8)),
        )
        sess.add(p)
        await sess.commit()
        await sess.refresh(p)
    return {"id": p.id, "domain": p.domain, "pattern_name": p.pattern_name, "created": True}


@router.put("/intelligence/global-patterns/{pattern_id}")
async def update_global_pattern(
    pattern_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Admin: update a GlobalPattern to correct learned behavior."""
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import GlobalPattern
    sf = get_session_factory()
    async with sf() as sess:
        p = await sess.get(GlobalPattern, pattern_id)
        if not p:
            raise HTTPException(status_code=404, detail="Pattern not found")
        if p.org_id != user["org_id"]:
            raise HTTPException(status_code=403, detail="not_your_pattern")
        for field_name in ("domain", "pattern_name", "pattern_type", "success_rate", "usage_count", "avg_quality_score"):
            if field_name in body:
                setattr(p, field_name, body[field_name])
        await sess.commit()
        await sess.refresh(p)
    return {"id": p.id, "domain": p.domain, "pattern_name": p.pattern_name, "updated": True}


@router.delete("/intelligence/global-patterns/{pattern_id}", status_code=204)
async def delete_global_pattern(
    pattern_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """Admin: delete a GlobalPattern entry to remove incorrect learned behaviors."""
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import GlobalPattern
    sf = get_session_factory()
    async with sf() as sess:
        p = await sess.get(GlobalPattern, pattern_id)
        if not p:
            raise HTTPException(status_code=404, detail="Pattern not found")
        if p.org_id != user["org_id"]:
            raise HTTPException(status_code=403, detail="not_your_pattern")
        await sess.delete(p)
        await sess.commit()


@router.get("/intelligence/quality-benchmark")
async def get_quality_benchmark(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    """Quality benchmark aggregated from real completed run data."""
    from aether_os.core.db import get_session_factory as _gsf_qb
    from sqlalchemy import text as _qt
    org_id = user["org_id"]
    try:
        async with _gsf_qb()() as _sess_qb:
            total = (await _sess_qb.execute(
                _qt("SELECT COUNT(*) FROM runs WHERE org_id=:oid AND status='completed'"),
                {"oid": org_id},
            )).scalar() or 0
            domain_rows = (await _sess_qb.execute(
                _qt("SELECT domain, COUNT(*) FROM runs WHERE org_id=:oid AND status='completed'"
                    " AND domain IS NOT NULL GROUP BY domain"),
                {"oid": org_id},
            )).all()
            domain_counts = {r[0]: r[1] for r in domain_rows}
            max_count = max(domain_counts.values()) if domain_counts else 1
            domain_scores = {d: min(100, round(70 + 30 * c / max_count)) for d, c in domain_counts.items()}
    except Exception as e:
        logger.warning("intelligence_router: failed to compute learning score: %s", e)
        total, domain_scores = 0, {}
    overall = round(sum(domain_scores.values()) / max(len(domain_scores), 1), 1) if domain_scores else 0.0
    return {
        "overall_score": overall,
        "baseline_score": 70.0,
        "completed_runs": total,
        "domains": domain_scores,
    }


@router.post("/intelligence/arch-governor/review")
async def arch_governor_review(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """T9-01: Review generated code against architecture spec."""
    from aether_os.core.intelligence.arch_governor import get_arch_governor
    gov = get_arch_governor()
    run_id = req.get("run_id", "")
    result = await gov.enforce(
        run_id=run_id,
        architecture_doc=req.get("architecture_doc", ""),
        generated_code=req.get("generated_code", ""),
        org_id=user.get("org_id"),
    )
    return result


@router.post("/intelligence/truth-engine/validate")
async def truth_engine_validate(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """T9-02: Validate requirements coverage in generated output."""
    from aether_os.core.intelligence.truth_engine import get_truth_engine
    engine = get_truth_engine()
    if run_id := req.get("run_id"):
        return await engine.audit_run(run_id)
    return await engine.validate(
        requirements=req.get("requirements", ""),
        generated_code=req.get("generated_code", ""),
        architecture_doc=req.get("architecture_doc", ""),
    )


@router.post("/intelligence/conflict-resolver/detect")
async def conflict_resolver_detect(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """T9-03: Detect conflicts in requirements or architecture."""
    from aether_os.core.intelligence.conflict_resolver import get_conflict_resolver
    resolver = get_conflict_resolver()
    return await resolver.detect(
        requirements=req.get("requirements", ""),
        constraints=req.get("constraints", ""),
        architecture_doc=req.get("architecture_doc", ""),
    )


@router.post("/intelligence/conflict-resolver/resolve")
async def conflict_resolver_resolve(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """T9-03: Record a conflict resolution."""
    from aether_os.core.intelligence.conflict_resolver import get_conflict_resolver
    resolver = get_conflict_resolver()
    return await resolver.resolve(
        conflict_id=req.get("conflict_id", ""),
        resolution=req.get("resolution", ""),
        run_id=req.get("run_id", ""),
        org_id=user.get("org_id"),
    )


@router.post("/intelligence/tradeoff-engine/analyze")
async def tradeoff_engine_analyze(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """T9-04: Analyze architectural tradeoffs between two options."""
    from aether_os.core.intelligence.tradeoff_engine import get_tradeoff_engine
    engine = get_tradeoff_engine()
    return await engine.analyze(
        option_a=req.get("option_a", ""),
        option_b=req.get("option_b", ""),
        requirements=req.get("requirements", ""),
        domain=req.get("domain", "general"),
    )


@router.post("/intelligence/improvement-loop/cycle")
async def improvement_loop_cycle(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """T9-05: Run a full improvement loop cycle for a completed run."""
    from aether_os.core.intelligence.improvement_loop import get_improvement_loop
    loop = get_improvement_loop()
    return await loop.run_cycle(run_id, org_id=user.get("org_id"))


@router.post("/intelligence/maintenance-engine/scan")
async def maintenance_engine_scan(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """T9-06: Scan dependencies and/or analyze tech debt."""
    from aether_os.core.intelligence.maintenance_engine import get_maintenance_engine
    engine = get_maintenance_engine()
    results = {}
    if req.get("requirements_txt"):
        results["dependencies"] = await engine.scan_dependencies(req["requirements_txt"])
    if req.get("code"):
        results["tech_debt"] = await engine.tech_debt_analysis(req["code"], req.get("language", "python"))
    if req.get("run_id"):
        results["health"] = await engine.health_check_project(req["run_id"])
    return results


@router.get("/intelligence/maintenance-engine/health/{run_id}")
async def maintenance_health_check(run_id: str, user: Dict[str, Any] = _current_user()):
    """T9-06: Health check for a project run."""
    from aether_os.core.intelligence.maintenance_engine import get_maintenance_engine
    engine = get_maintenance_engine()
    return await engine.health_check_project(run_id)
