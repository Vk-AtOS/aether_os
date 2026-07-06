"""AetherOS — Factory Runs Router (core run lifecycle).

GET /factory/runs, GET/POST /factory/runs/{run_id} (detail, quality, priority, rerun, branch).
Files/snapshots → factory_run_files_router
Streaming/SSE  → factory_run_streaming_router
Compliance     → factory_run_compliance_router
"""
from __future__ import annotations

import asyncio
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

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])


# ── Pydantic models ────────────────────────────────────────────────────────────

class PriorityRequest(BaseModel):
    priority: str  # "high" | "normal" | "low"


class RerunRequest(BaseModel):
    from_phase: str


# ── Auth helper ────────────────────────────────────────────────────────────────

def _current_user():
    return Depends(get_current_user)


# ── Module-level shared state (mirrors api.py globals) ────────────────────────

def _get_background_tasks() -> set:
    from aether_os.gateway import api as _api
    return _api._background_tasks


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/factory/runs/{run_id}/test-report")
async def get_test_report(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get the self-test report for a run."""
    from aether_os.core.db import get_session_factory

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
        from aether_os.core.audit.ledger import get_ledger
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
                from aether_os.core.db import get_session_factory as _gsf
                async with _gsf()() as _sess:
                    await enrich_runs_with_quality(_sess, items)
            except Exception as _e:
                logger.debug("quality_score enrichment failed: %s", _e)

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
    from aether_os.core.audit.ledger import get_ledger
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
        from aether_os.core.db import get_session_factory as _gsf3
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
        from aether_os.core.quality.metrics import score_project
        from dataclasses import asdict as _asdict
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
    from aether_os.core.audit.ledger import get_ledger
    from aether_os.core.projects import get_project_manager
    from aether_os.core.quality.metrics import score_project
    from dataclasses import asdict

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
    from aether_os.core.audit.ledger import get_ledger
    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if req.priority not in ("high", "normal", "low"):
        raise HTTPException(status_code=400, detail="priority must be high | normal | low")

    # Upsert priority via ORM (FIX-017)
    from aether_os.core.db import get_session_factory as _gsf_pri
    from aether_os.core.models import RunMetadata as _RM_pri

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


@router.post("/factory/runs/{run_id}/rerun")
async def rerun_factory_run(
    run_id: str,
    req: RerunRequest,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Create a new run starting from a given phase."""
    import uuid as _uuid
    from aether_os.orchestrator.factory_pipeline import get_factory as _get_factory
    from aether_os.core.audit.ledger import get_ledger

    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    from sqlalchemy import select, update as _sa_upd

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Organisation).where(Organisation.id == org_id)
        result = await session.execute(stmt)
        org = result.scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        if org.plan == "trial":
            # Atomic increment — prevents TOCTOU race (K-04)
            upd = await session.execute(
                _sa_upd(Organisation)
                .where(Organisation.id == org_id)
                .where(Organisation.trial_runs_used < Organisation.trial_runs_limit)
                .values(trial_runs_used=Organisation.trial_runs_used + 1)
            )
            await session.commit()
            if upd.rowcount == 0:
                raise HTTPException(
                    status_code=402,
                    detail={"error": "trial_limit_reached", "upgrade_url": "/pricing"},
                )

    cmd = detail.get("command", "")
    raw_input = cmd[9:] if cmd.startswith("factory: ") else cmd
    new_run_id = str(_uuid.uuid4())
    factory = _get_factory()
    _background_tasks = _get_background_tasks()

    async def _bg():
        try:
            await factory.run(
                client_id=user.get("org_slug", "rerun"),
                raw_input=raw_input,
                start_phase=req.from_phase,
                run_id=new_run_id,
                org_id=org_id,
            )
        except Exception as exc:
            logger.error("Rerun failed: %s", exc)

    _t = asyncio.create_task(_bg())
    _background_tasks.add(_t)
    _t.add_done_callback(_background_tasks.discard)
    return {"run_id": new_run_id, "status": "started", "from_phase": req.from_phase}


@router.post("/factory/runs/{run_id}/branch")
async def branch_factory_run(
    run_id: str,
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Fork a run at a given phase — creates a new run with the same context."""
    import uuid as _uuid2
    from aether_os.orchestrator.factory_pipeline import get_factory as _get_factory2
    from aether_os.core.db import get_session_factory as _gsf_b
    from aether_os.core.models import Run as _RunB
    from sqlalchemy import select as _sel_b

    branch_phase = req.get("branch_phase", "p04_backend")
    extra_input = req.get("extra_input", "")
    org_id = user.get("org_id")
    async with _gsf_b()() as _s:
        parent = (
            await _s.execute(
                _sel_b(_RunB).where(_RunB.id == run_id, _RunB.org_id == org_id)
            )
        ).scalar_one_or_none()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent run not found")

    new_run_id = str(_uuid2.uuid4())
    raw_input = (parent.raw_input or parent.command or "").replace("factory: ", "")
    if extra_input:
        raw_input = f"{raw_input}\n\nAdditional requirement: {extra_input}"

    # Mark branch in DB
    async with _gsf_b()() as _s:
        branch_row = _RunB(
            id=new_run_id, org_id=org_id, status="queued",
            parent_run_id=run_id, branch_phase=branch_phase,
            raw_input=raw_input, domain=parent.domain or "general",
            project_name=f"{parent.project_name or 'project'} (branch)",
            started_at=__import__("time").time(),
        )
        _s.add(branch_row)
        await _s.commit()

    factory = _get_factory2()
    _background_tasks = _get_background_tasks()

    async def _branch_bg():
        try:
            await factory.run(
                client_id=user.get("org_slug", "branch"),
                raw_input=raw_input,
                start_phase=branch_phase,
                run_id=new_run_id,
                org_id=org_id,
                domain=parent.domain or "general",
            )
        except Exception as exc:
            logger.error("Branch run failed: %s", exc)

    _bt = asyncio.create_task(_branch_bg())
    _background_tasks.add(_bt)
    _bt.add_done_callback(_background_tasks.discard)
    return {
        "run_id": new_run_id,
        "status": "started",
        "parent_run_id": run_id,
        "branch_phase": branch_phase,
    }
