"""
AetherOS — Factory Analytics Router
Extracted from factory_ops_router.py.

Routes for run analytics and deployment status:
  GET /factory/analytics/quality-trend
  GET /analytics/quality-trend
  GET /factory/search
  GET /factory/deployments
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from aether_os.core.run_app import safe_fs
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["factory"])


def _current_user():
    return Depends(get_current_user)


@router.get("/factory/analytics/quality-trend")
async def get_quality_trend(
    limit: int = 50,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return quality + compliance scores for recent completed runs — proves cross-run improvement."""
    from aether_os.core.db import get_session_factory as _gsf_qt
    from sqlalchemy import text as _qt_text
    import pathlib as _pathlib

    org_id = user["org_id"]
    _limit = max(1, min(limit, 200))

    # Fetch recent completed runs from DB — include cached quality_score column
    try:
        async with _gsf_qt()() as _sess:
            rows = (await _sess.execute(
                _qt_text(
                    "SELECT id, project_name, started_at, quality_score FROM runs "
                    "WHERE org_id=:oid AND status IN ('completed','passed') "
                    "ORDER BY started_at DESC LIMIT :lim"
                ),
                {"oid": org_id, "lim": _limit},
            )).all()
    except Exception as _qt_exc:
        logger.debug("quality-trend DB query failed: %s", _qt_exc)
        rows = []

    points = []
    projects_dir = _pathlib.Path.home() / ".aether_os" / "projects"

    for row in rows:
        run_id_qt, proj_name, started_at_qt, db_quality_score = row[0], row[1], row[2], row[3]

        # Convert epoch float to ISO string
        try:
            from datetime import datetime as _dt, timezone as _tz
            _ts = float(started_at_qt) if started_at_qt else 0.0
            created_at_iso = _dt.fromtimestamp(_ts, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception as exc:
            logger.debug("Failed to convert started_at timestamp %r to ISO string: %s", started_at_qt, exc)
            created_at_iso = str(started_at_qt)

        # Use cached DB quality_score first; fall back to on-demand compute only if absent
        quality_score: Optional[int] = db_quality_score
        if quality_score is None:
            run_dir = projects_dir / run_id_qt
            if run_dir.exists():
                try:
                    from aether_os.core.quality.metrics import score_project as _score_qt
                    _qs = _score_qt(run_dir)
                    quality_score = _qs.total
                except Exception as exc:
                    logger.debug("Quality score calculation failed for run %s: %s", run_id_qt, exc)

        # Compliance score from pre-built scan JSON
        compliance_score: Optional[int] = None
        run_dir = projects_dir / run_id_qt
        # safe_fs: run_dir is writable by the sandboxed app; a planted link reads as absent
        _comp_text = safe_fs.read_text_or_none(run_dir, "p06_review_security/compliance/compliance_scan.json")
        if _comp_text is not None:
            try:
                _cd = json.loads(_comp_text)
                compliance_score = _cd.get("score")
            except Exception as exc:
                logger.debug("Failed to read compliance_scan.json for run %s: %s", run_id_qt, exc)

        if quality_score is not None:
            points.append({
                "run_id": run_id_qt,
                "project_name": proj_name or f"run-{run_id_qt[:8]}",
                "created_at": created_at_iso,
                "quality_score": quality_score,
                "compliance_score": compliance_score,
            })

    # Reverse so oldest is first (for chart to trend left→right in time)
    points.reverse()
    return {"points": points, "total": len(points)}


@router.get("/factory/search")
async def search_artifacts(
    q: str,
    limit: int = 30,
    user: Dict[str, Any] = _current_user(),
) -> List[Dict[str, Any]]:
    """Semantic search across all generated artifacts for the organisation."""
    from aether_os.core.artifact_store import get_artifact_store
    org_id = user.get("org_id")
    store = get_artifact_store()
    return await store.search(q, org_id, limit=limit)


@router.get("/factory/deployments")
async def list_deployments(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """List deployments: completed runs from DB plus running Docker containers."""
    import subprocess as _sp
    import asyncio as _aio

    org_id = user.get("org_id")

    # 1. Query completed/running runs from DB
    db_deployments: List[Dict[str, Any]] = []
    try:
        from aether_os.core.db import get_session_factory as _gsf_dep
        from aether_os.core.models import Run as _RunDep
        from sqlalchemy import select as _sel_dep
        async with _gsf_dep()() as _sess_dep:
            _run_rows = (await _sess_dep.execute(
                _sel_dep(_RunDep)
                .where(
                    _RunDep.org_id == org_id,
                    _RunDep.status.in_(["completed", "needs_review", "running"]),
                )
                .order_by(_RunDep.started_at.desc())
                .limit(50)
            )).scalars().all()
        for _r in _run_rows:
            # Note: _APP_PROCS lives in api.py; proc_status defaults to stopped in this router context
            db_deployments.append({
                "run_id":       _r.id,
                "project_name": _r.project_name or f"run-{_r.id[:8]}",
                "domain":       _r.domain or "general",
                "status":       _r.status,
                "proc_status":  "stopped",
                "started_at":   _r.started_at,
                "live_url":     getattr(_r, "live_url", None),
            })
    except Exception as _dep_exc:
        logger.debug("Deployments DB query failed: %s", _dep_exc)

    # 2. List running Docker containers (best-effort — docker may not be in PATH inside container)
    containers = []
    try:
        def _list():
            return _sp.run(
                ["docker", "ps", "--filter", "name=aetheros-app",
                 "--format", "{{.Names}}\t{{.Ports}}\t{{.Status}}"],
                capture_output=True, text=True,
            )

        result = await _aio.to_thread(_list)
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split("\t")
                containers.append({
                    "name":   parts[0] if len(parts) > 0 else "",
                    "ports":  parts[1] if len(parts) > 1 else "",
                    "status": parts[2] if len(parts) > 2 else "",
                })
    except Exception as exc:
        logger.debug("Docker container listing failed (docker may not be in PATH): %s", exc)
    return {"deployments": db_deployments, "containers": containers}


@router.get("/analytics/quality-trend")
async def daily_quality_trend(
    days: int = Query(30, ge=1, le=365, description="Number of past days to include"),
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """
    Return daily quality metrics for the last N days.

    Each entry contains the number of runs that day, the success rate
    (status='completed' or 'passed' vs total), and average phase confidence
    extracted from checkpoint_data.accumulated_context.phase_confidence.
    Days with no runs are omitted.
    """
    from aether_os.core.db import get_session_factory as _gsf_dqt
    from aether_os.core.models import Run as _RunDqt
    from sqlalchemy import select as _sel_dqt

    org_id = user["org_id"]
    cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()

    try:
        async with _gsf_dqt()() as _sess:
            rows = (await _sess.execute(
                _sel_dqt(_RunDqt)
                .where(
                    _RunDqt.org_id == org_id,
                    _RunDqt.started_at >= cutoff_ts,
                )
                .order_by(_RunDqt.started_at.asc())
            )).scalars().all()
    except Exception as exc:
        logger.warning("analytics: daily_quality_trend DB query failed: %s", exc)
        rows = []

    # Group runs by calendar date (UTC)
    day_buckets: Dict[str, Dict[str, Any]] = {}
    for run in rows:
        try:
            date_key = datetime.fromtimestamp(
                float(run.started_at), tz=timezone.utc
            ).strftime("%Y-%m-%d")
        except Exception as exc:
            logger.debug("analytics: bad started_at %r: %s", run.started_at, exc)
            continue

        bucket = day_buckets.setdefault(date_key, {"runs": 0, "succeeded": 0, "confidences": []})
        bucket["runs"] += 1
        if run.status in ("completed", "passed"):
            bucket["succeeded"] += 1

        # Extract average phase confidence for this run
        checkpoint = run.checkpoint_data or {}
        phase_conf = checkpoint.get("accumulated_context", {}).get("phase_confidence", {})
        if isinstance(phase_conf, dict) and phase_conf:
            conf_vals = [v for v in phase_conf.values() if isinstance(v, (int, float))]
            if conf_vals:
                bucket["confidences"].append(sum(conf_vals) / len(conf_vals))

    trend = []
    for date_key in sorted(day_buckets.keys()):
        b = day_buckets[date_key]
        total_runs = b["runs"]
        success_rate = round(b["succeeded"] / total_runs, 4) if total_runs else 0.0
        confs = b["confidences"]
        avg_conf: Optional[float] = round(sum(confs) / len(confs), 4) if confs else None
        trend.append({
            "date": date_key,
            "runs": total_runs,
            "success_rate": success_rate,
            "avg_confidence": avg_conf,
        })

    return {"trend": trend, "days": days, "total_runs": sum(b["runs"] for b in day_buckets.values())}
