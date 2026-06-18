"""
AetherOS — Factory Analytics Router
Extracted from factory_ops_router.py.

Routes for run analytics and deployment status:
  GET /factory/analytics/quality-trend
  GET /factory/search
  GET /factory/deployments
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
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
        except Exception:
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
                except Exception:
                    pass

        # Compliance score from pre-built scan JSON
        compliance_score: Optional[int] = None
        run_dir = projects_dir / run_id_qt
        _comp_json = run_dir / "p06_review_security" / "compliance" / "compliance_scan.json"
        if _comp_json.exists():
            try:
                _cd = json.loads(_comp_json.read_text(encoding="utf-8"))
                compliance_score = _cd.get("score")
            except Exception:
                pass

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
    except Exception:
        pass
    return {"deployments": db_deployments, "containers": containers}
