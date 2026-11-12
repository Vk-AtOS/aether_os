"""AetherOS — Factory Runs Router (core run lifecycle).

GET /factory/runs, GET/POST /factory/runs/{run_id} (detail, quality, priority).
Rerun/branch    → run_fork_router
Files/snapshots → factory_run_files_router
Streaming/SSE  → factory_run_streaming_router
Compliance     → factory_run_compliance_router
"""
from __future__ import annotations

import json
import logging
import pathlib
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers.factory_run_background import (
    enrich_phases_from_disk,
    load_phase_events,
)
from aether_os.core.services.run_service import (
    get_test_report as svc_get_test_report,
    enrich_runs_with_quality,
    get_phase_completions,
    get_explicit_events,
    get_run_priority_and_live_url,
)
from dataclasses import asdict
from dataclasses import asdict as _asdict
from sqlalchemy import select as _sel_ev
from aether_os.core.quality.metrics import score_project
from aether_os.core.projects import get_project_manager
from aether_os.core.models import RunMetadata as _RM_pri
from aether_os.core.models import PipelineEvent
from aether_os.core.db import get_session_factory
from aether_os.core.db import get_session_factory as _gsf
from aether_os.core.db import get_session_factory as _gsf_pri
from aether_os.core.db import get_session_factory as _gsf_ev
from aether_os.core.db import get_session_factory as _gsf3
from aether_os.core.audit.ledger import get_ledger

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])

# ── Pydantic models ────────────────────────────────────────────────────────────

class PriorityRequest(BaseModel):
    priority: str  # "high" | "normal" | "low"

# ── Auth helper ────────────────────────────────────────────────────────────────

def _current_user():
    return Depends(get_current_user)

# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/factory/runs/{run_id}/test-report")
async def get_test_report(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get the self-test report for a run."""

    async with get_session_factory()() as session:
        report_str = await svc_get_test_report(session, run_id, user["org_id"])

    if not report_str:
        raise HTTPException(status_code=404, detail="Report not found")

    return json.loads(report_str)

@router.get("/factory/runs")
async def list_factory_runs(
    user: Dict[str, Any] = _current_user(),
    page: int = 1,
    limit: int = 50,
    cursor: Optional[float] = None,
) -> Dict[str, Any]:
    """List pipeline runs for the organisation with cursor-based pagination.

    Prefer cursor-based pagination for all pages after the first:
      GET /factory/runs?limit=50              → first page, returns next_cursor
      GET /factory/runs?limit=50&cursor=<ts>  → next page (fast keyset seek)

    Legacy page/offset mode is also supported for backward compatibility but
    degrades at high page numbers due to OFFSET scan cost.
    """
    limit = min(max(limit, 1), 100)
    page = max(page, 1)
    # Only compute offset for legacy callers that pass page > 1 without a cursor
    offset = 0 if cursor is not None else (page - 1) * limit
    try:

        org_id = user.get("org_id")
        result = await get_ledger().async_get_run_history(
            org_id=org_id, limit=limit, offset=offset, cursor=cursor
        )
        items = result.get("items", [])
        total = result.get("total", len(items))
        next_cursor = result.get("next_cursor")

        # Enrich with quality_score from Run table
        if items:
            try:

                async with _gsf()() as _sess:
                    await enrich_runs_with_quality(_sess, items)
            except Exception as _e:
                logger.warning("quality_score enrichment failed (run list will show no scores): %s", _e)

        return {
            "items": items,
            "page": page,
            "limit": limit,
            "total": total,
            "next_cursor": next_cursor,
        }
    except Exception as exc:
        logger.warning("Could not fetch run history: %s", exc)
        return {"items": [], "page": page, "limit": limit, "total": 0, "next_cursor": None}

@router.get("/factory/runs/{run_id}")
async def get_factory_run(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get detail for a single pipeline run."""

    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    # Enrich with phase_completions + events via async ORM (FIX-017)
    phases, current_phase, events = await load_phase_events(
        run_id, get_phase_completions, get_explicit_events
    )
    detail["events"] = events if events else detail.get("events", [])

    detail["phases"] = phases
    detail["current_phase"] = current_phase
    # Only derive project_name from command if DB field is empty
    if not detail.get("project_name"):
        cmd = detail.get("command", "")
        detail["project_name"] = cmd[9:] if cmd.startswith("factory: ") else cmd
    detail.setdefault("cost", 0.0)

    # Enrich each phase with output files from disk, gate results, and strip server paths.
    # Logic extracted to factory_run_background.enrich_phases_from_disk to keep this router lean.
    project_dir = pathlib.Path.home() / ".aether_os" / "projects" / run_id
    _project_prefix = str(project_dir) + "/"
    detail["phases"] = enrich_phases_from_disk(phases, project_dir, _project_prefix)

    # Enrich p06 with actual security findings from security_report.json
    if "p06_review_security" in detail.get("phases", {}):
        _sec_report = (
            project_dir / "p06_review_security" / "security" / "security_report.json"
        )
        if _sec_report.exists():
            try:
                _sec_data = json.loads(_sec_report.read_text(encoding="utf-8"))
                detail["phases"]["p06_review_security"].setdefault("output", {})
                detail["phases"]["p06_review_security"]["output"]["security_findings"] = (
                    _sec_data.get("findings", [])
                )
                detail["phases"]["p06_review_security"]["output"]["security_total"] = (
                    _sec_data.get("total", 0)
                )
            except Exception as exc:
                logger.debug(
                    "Failed to load security_report.json for run %s: %s", run_id, exc
                )

    # Load priority and live_url via ORM (FIX-017)
    detail.setdefault("live_url", None)
    try:

        _sf3 = _gsf3()
        async with _sf3() as _sess3:
            priority, live_url = await get_run_priority_and_live_url(_sess3, run_id, org_id)
            if live_url:
                detail["live_url"] = live_url
    except Exception as _e3:
        logger.debug("Priority/live_url ORM query failed: %s", _e3)
        priority = "normal"
    detail["priority"] = priority

    # Enrich with quality score if project output exists (best-effort, non-blocking)
    try:

        _qdir = pathlib.Path.home() / ".aether_os" / "projects" / run_id
        if _qdir.exists():
            _qscore = score_project(_qdir)
            detail["quality"] = _asdict(_qscore)
    except Exception as _qe:
        logger.debug("Quality score enrichment failed for run %s: %s", run_id, _qe)

    return detail

@router.get("/factory/runs/{run_id}/quality")
async def get_run_quality(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get quality score for a completed run's generated output."""

    # B2: verify run belongs to this org before touching the filesystem (IDOR fix)
    org_id = user.get("org_id")
    run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not run_detail:
        raise HTTPException(status_code=404, detail="Run not found")

    project_dir = get_project_manager().get_project_dir(run_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project output not found")

    try:
        score = score_project(project_dir)
    except Exception as exc:
        logger.warning("quality score failed for run %s: %s", run_id, exc)
        raise HTTPException(status_code=500, detail=f"Quality scoring failed: {exc}")

    return {"run_id": run_id, "quality": asdict(score)}

@router.post("/factory/runs/{run_id}/priority")
async def set_factory_run_priority(
    run_id: str,
    req: PriorityRequest,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Set the priority label for a run."""

    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if req.priority not in ("high", "normal", "low"):
        raise HTTPException(status_code=400, detail="priority must be high | normal | low")

    # Upsert priority via ORM (FIX-017)

    _sf_pri = _gsf_pri()
    async with _sf_pri() as _sess_pri:
        existing = await _sess_pri.get(_RM_pri, run_id)
        if existing:
            existing.priority = req.priority
            existing.updated_at = time.time()
        else:
            _sess_pri.add(
                _RM_pri(run_id=run_id, priority=req.priority, updated_at=time.time())
            )
        await _sess_pri.commit()
    return {"run_id": run_id, "priority": req.priority}

@router.get("/factory/runs/{run_id}/events")
async def get_run_events(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return all pipeline events for a run, ordered by created_at.

    M11: RunDetail.jsx calls this route but no handler existed — events tab was always empty.
    Queries the pipeline_events table (created in DB-C1 migration).
    """

    # Verify run belongs to this org (IDOR guard)
    org_id = user.get("org_id")
    run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not run_detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    try:
        async with _gsf_ev()() as _sess_ev:
            rows = (
                await _sess_ev.execute(
                    _sel_ev(PipelineEvent)
                    .where(PipelineEvent.run_id == run_id)
                    .order_by(PipelineEvent.created_at.asc())
                )
            ).scalars().all()
    except Exception as exc:
        logger.warning("get_run_events: DB query failed for run %s: %s", run_id, exc)
        rows = []

    events = [
        {
            "id": e.id,
            "run_id": e.run_id,
            "phase": (e.payload or {}).get("phase") if e.payload else None,
            "event_type": e.event_type,
            "payload": e.payload,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]
    return {"run_id": run_id, "events": events, "total": len(events)}
