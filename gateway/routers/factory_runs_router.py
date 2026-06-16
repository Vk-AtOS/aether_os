"""
AetherOS — Factory Runs Router
Extracted from gateway/api.py

Routes:
  GET  /factory/runs/{run_id}/test-report
  GET  /factory/runs
  GET  /factory/runs/{run_id}
  GET  /factory/runs/{run_id}/quality
  GET  /factory/runs/{run_id}/snapshots
  GET  /factory/runs/{run_id}/snapshots/{snapshot_id}
  POST /factory/runs/{run_id}/memory/changelog
  POST /factory/runs/{run_id}/pause
  POST /factory/runs/{run_id}/resume
  POST /factory/runs/{run_id}/restart
  POST /factory/runs/{run_id}/cancel
  POST /factory/runs/{run_id}/priority
  POST /factory/runs/{run_id}/rerun
  POST /factory/runs/{run_id}/branch
  POST /factory/runs/{run_id}/sse-token
  GET  /factory/runs/{run_id}/stream
  GET  /factory/runs/{run_id}/preview
  GET  /factory/runs/{run_id}/files
  GET  /factory/runs/{run_id}/file-content
  PATCH /factory/runs/{run_id}/file-content
  POST /factory/runs/{run_id}/open-in-vscode
  GET  /factory/runs/{run_id}/envvars
  PATCH /factory/runs/{run_id}/envvars
  POST /factory/runs/{run_id}/run-app
  DELETE /factory/runs/{run_id}/run-app
  GET  /factory/runs/{run_id}/run-app/status
  GET  /factory/runs/{run_id}/compliance
  GET  /factory/runs/{run_id}/decisions
  POST /factory/runs/{run_id}/decisions/{decision_id}/approve
  POST /factory/runs/{run_id}/decisions/{decision_id}/decide
  POST /factory/runs/{run_id}/council-review
  GET  /factory/runs/{run_id}/council-review
  POST /factory/runs/{run_id}/kill
  POST /factory/runs/{run_id}/deploy
  DELETE /factory/runs/{run_id}/deploy
  GET  /factory/runs/{run_id}/artifacts
  GET  /factory/runs/{run_id}/download
  POST /factory/runs/{run_id}/push-github
  GET  /factory/runs/{run_id}/frontend-spec
  POST /factory/runs/{run_id}/frontend-spec
  GET  /factory/runs/{run_id}/backend-spec
  POST /factory/runs/{run_id}/backend-spec
  POST /factory/runs/{run_id}/validate-spec
  POST /factory/runs/{run_id}/chat
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import tempfile
import textwrap
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user

# EventSourceResponse imported lazily inside the stream endpoint to avoid hard dep at module load

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])


# ── Pydantic models (local copies for this router) ────────────────────────────

class PriorityRequest(BaseModel):
    priority: str  # "high" | "normal" | "low"


class RerunRequest(BaseModel):
    from_phase: str


class FileWriteBody(BaseModel):
    path: str
    content: str


class EnvVarItem(BaseModel):
    key: str
    value: str


class EnvVarsBody(BaseModel):
    vars: List[EnvVarItem]


# ── Auth helper ────────────────────────────────────────────────────────────────

def _current_user():
    return Depends(get_current_user)


# ── Module-level shared state (mirrors api.py globals) ────────────────────────

def _get_background_tasks() -> set:
    from aether_os.gateway import api as _api
    return _api._background_tasks


def _get_app_procs() -> Dict[str, Any]:
    from aether_os.core.app_state import get_all_procs
    return get_all_procs()


class _ExternalProcess:
    """Lightweight PID wrapper so recovered processes behave like Popen objects."""
    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):
        try:
            os.kill(self.pid, 0)
            return None  # alive
        except (ProcessLookupError, PermissionError):
            return 1  # dead

    def terminate(self):
        try:
            import signal as _sig
            os.kill(self.pid, _sig.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def kill(self):
        try:
            import signal as _sig
            os.kill(self.pid, _sig.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def wait(self, timeout=None):
        pass


def _get_sse_fns():
    from aether_os.core.rate_limiter import sse_token_set, sse_token_pop
    return sse_token_set, sse_token_pop


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/factory/runs/{run_id}/test-report")
async def get_test_report(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get the self-test report for a run."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Run).where(Run.id == run_id, Run.org_id == user["org_id"])
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()

        if not run or not run.self_test_report:
            raise HTTPException(status_code=404, detail="Report not found")

        return json.loads(run.self_test_report)


@router.get("/factory/runs")
async def list_factory_runs(
    user: Dict[str, Any] = _current_user(),
    page: int = 1,
    limit: int = 50,
) -> Dict[str, Any]:
    """List pipeline runs for the organisation with pagination."""
    limit = min(max(limit, 1), 100)
    page = max(page, 1)
    offset = (page - 1) * limit
    try:
        from aether_os.core.audit.ledger import get_ledger
        org_id = user.get("org_id")
        result = await get_ledger().async_get_run_history(
            org_id=org_id, limit=limit, offset=offset
        )
        items = result.get("items", [])
        total = result.get("total", len(items))

        # Enrich with quality_score from Run table (phase/priority/live_url already in items)
        if items:
            try:
                from aether_os.core.db import get_session_factory as _gsf
                from aether_os.core.models import Run as _Run
                from sqlalchemy import select as _sel
                _run_ids = [r.get("id") for r in items if r.get("id")]
                async with _gsf()() as _sess:
                    _qs_rows = (await _sess.execute(
                        _sel(_Run.id, _Run.quality_score).where(_Run.id.in_(_run_ids))
                    )).all()
                _qs_map = {rid: qs for rid, qs in _qs_rows if qs is not None}
                for item in items:
                    item.setdefault("quality_score", _qs_map.get(item.get("id")))
            except Exception as _e:
                logger.debug("quality_score enrichment failed: %s", _e)

        return {"items": items, "page": page, "limit": limit, "total": total}
    except Exception as exc:
        logger.warning("Could not fetch run history: %s", exc)
        return {"items": [], "page": page, "limit": limit, "total": 0}


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

    # db_utils already converts timestamps to ms — no further conversion needed

    # Enrich with phase_completions via async ORM (FIX-017)
    phases: Dict[str, Any] = {}
    current_phase = None
    synthesized_events: list = []
    try:
        from aether_os.core.db import get_session_factory as _gsf2
        from aether_os.core.models import PhaseCompletion as _PC2, Event as _Ev2
        from sqlalchemy import select as _sel2
        _sf2 = _gsf2()
        async with _sf2() as _sess2:
            _pc2_rows = (await _sess2.execute(
                _sel2(_PC2.phase_name, _PC2.status, _PC2.updated_at)
                .where(_PC2.run_id == run_id, _PC2.phase_name != "pipeline")
                .order_by(_PC2.updated_at.asc())
            )).all()
            for _phase, _status, _updated in _pc2_rows:
                phases[_phase] = {"status": _status, "updated_at": _updated}
                current_phase = _phase
                # Synthesize an agent event from each phase completion
                _label = _phase.replace("_", " ").replace("p0", "Phase ").replace("p1", "Phase 1")
                # Fix 65: updated_at may be a float (epoch) or a datetime object
                if hasattr(_updated, "timestamp"):
                    _ts = _updated.timestamp()
                elif isinstance(_updated, (int, float)) and _updated:
                    _ts = float(_updated)
                else:
                    _ts = None
                synthesized_events.append({
                    "agent": _label.title(),
                    "action": _status,
                    "detail": f"{_label.title()} {_status}",
                    "timestamp": _ts,
                })
            # Also pull any explicit Event rows
            _ev_rows = (await _sess2.execute(
                _sel2(_Ev2.agent, _Ev2.action, _Ev2.detail, _Ev2.timestamp)
                .where(_Ev2.run_id == run_id)
                .order_by(_Ev2.timestamp.asc())
            )).all()
            explicit_events = [
                {"agent": r[0], "action": r[1], "detail": r[2], "timestamp": r[3]}
                for r in _ev_rows
            ]
            # Use explicit events if available, otherwise use synthesized
            detail["events"] = explicit_events if explicit_events else synthesized_events
    except Exception as _e2:
        logger.debug("Phase completions ORM query failed: %s", _e2)
        detail.setdefault("events", [])

    detail["phases"] = phases
    detail["current_phase"] = current_phase
    # Only derive project_name from command if DB field is empty
    if not detail.get("project_name"):
        cmd = detail.get("command", "")
        detail["project_name"] = cmd[9:] if cmd.startswith("factory: ") else cmd
    detail.setdefault("cost", 0.0)

    # Enrich each phase with its output file content from the project dir
    project_dir = pathlib.Path.home() / ".aether_os" / "projects" / run_id
    _project_prefix = str(project_dir) + "/"
    _OUTPUT_FILE_CANDIDATES = [
        "consolidated.json", "architecture.json", "frontend_meta.json",
        "review.json", "test_results.json", "delivery.json",
        "observability.json", "cicd.json",
    ]
    for phase_key, phase_val in phases.items():
        phase_dir = project_dir / phase_key
        if not phase_dir.exists():
            continue
        # Try known names first
        loaded = False
        for fname in _OUTPUT_FILE_CANDIDATES + [f"{phase_key}.json"]:
            fpath = phase_dir / fname
            if fpath.exists():
                try:
                    phase_val["output"] = json.loads(fpath.read_text(encoding="utf-8"))
                    phase_val["output_file"] = f"{phase_key}/{fname}"
                    loaded = True
                    break
                except Exception:
                    pass
        # Fallback: first .json file directly in the phase dir
        if not loaded:
            for fpath in sorted(phase_dir.glob("*.json")):
                try:
                    phase_val["output"] = json.loads(fpath.read_text(encoding="utf-8"))
                    phase_val["output_file"] = f"{phase_key}/{fpath.name}"
                    break
                except Exception:
                    pass

    # Load gate_result.json for each phase if it exists
    for _pk, _pv in phases.items():
        _gate_file = project_dir / _pk / "gate_result.json"
        if _gate_file.exists():
            try:
                _pv["gate_result"] = json.loads(_gate_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    # Strip absolute server paths from all phase output (S8 security fix)
    def _strip_server_paths(obj):
        if isinstance(obj, str):
            return obj.replace(_project_prefix, "")
        if isinstance(obj, dict):
            return {k: _strip_server_paths(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_strip_server_paths(v) for v in obj]
        return obj
    detail["phases"] = _strip_server_paths(detail["phases"])

    # Enrich p06 with actual security findings from security_report.json
    if "p06_review_security" in detail.get("phases", {}):
        _sec_report = project_dir / "p06_review_security" / "security" / "security_report.json"
        if _sec_report.exists():
            try:
                _sec_data = json.loads(_sec_report.read_text(encoding="utf-8"))
                detail["phases"]["p06_review_security"].setdefault("output", {})
                detail["phases"]["p06_review_security"]["output"]["security_findings"] = _sec_data.get("findings", [])
                detail["phases"]["p06_review_security"]["output"]["security_total"] = _sec_data.get("total", 0)
            except Exception:
                pass

    # Load priority and live_url via ORM (FIX-017)
    priority = "normal"
    detail.setdefault("live_url", None)
    try:
        from aether_os.core.db import get_session_factory as _gsf3
        from aether_os.core.models import RunMetadata as _RM2, Run as _Run2
        from sqlalchemy import select as _sel3
        _sf3 = _gsf3()
        async with _sf3() as _sess3:
            _rm_row = (await _sess3.execute(
                _sel3(_RM2.priority).where(_RM2.run_id == run_id)
            )).scalar_one_or_none()
            if _rm_row:
                priority = _rm_row
            _run_row = (await _sess3.execute(
                _sel3(_Run2.live_url).where(_Run2.id == run_id, _Run2.org_id == org_id)
            )).scalar_one_or_none()
            if _run_row:
                detail["live_url"] = _run_row
    except Exception as _e3:
        logger.debug("Priority/live_url ORM query failed: %s", _e3)
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


# ── Code Snapshots ─────────────────────────────────────────────────────────────

@router.get("/factory/runs/{run_id}/snapshots")
async def list_run_snapshots(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """List all code snapshots for a run (versioned file history)."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run, Snapshot
    from sqlalchemy import select as _sel
    sf = get_session_factory()
    async with sf() as sess:
        run = await sess.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        rows = (await sess.execute(
            _sel(Snapshot)
            .where(Snapshot.run_id == run_id)
            .order_by(Snapshot.created_at.desc())
        )).scalars().all()
    return {
        "run_id": run_id,
        "snapshots": [
            {
                "id": s.id,
                "file_path": s.file_path,
                "created_at": s.created_at,
            }
            for s in rows
        ],
    }


@router.get("/factory/runs/{run_id}/snapshots/{snapshot_id}")
async def get_run_snapshot(
    run_id: str,
    snapshot_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get full content of a specific code snapshot."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run, Snapshot
    sf = get_session_factory()
    async with sf() as sess:
        run = await sess.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        snap = await sess.get(Snapshot, snapshot_id)
        if not snap or snap.run_id != run_id:
            raise HTTPException(status_code=404, detail="Snapshot not found")
    return {
        "id": snap.id,
        "run_id": snap.run_id,
        "file_path": snap.file_path,
        "content": snap.content,
        "created_at": snap.created_at,
    }


@router.post("/factory/runs/{run_id}/memory/changelog")
async def add_changelog(
    run_id: str,
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Add entry to project changelog."""
    from aether_os.core.memory.memory_manager import MemoryManager
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select
    from pathlib import Path

    session_factory = get_session_factory()
    async with session_factory() as session:
        # B2: filter by org_id to prevent IDOR cross-tenant access
        stmt = select(Run).where(Run.id == run_id, Run.org_id == user["org_id"])
        run = (await session.execute(stmt)).scalar_one_or_none()
        if not run: raise HTTPException(status_code=404)

        # Assuming project output dir is based on standard path logic
        project_dir = Path.home() / ".aether_os" / "projects" / run_id
        MemoryManager.add_changelog_entry(project_dir, req["entry"], user["sub"])
        return {"status": "ok"}


@router.post("/factory/runs/{run_id}/pause")
async def pause_factory_run(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Signal the pipeline to pause."""
    from aether_os.core.audit.ledger import get_ledger
    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    from aether_os.core.pipeline_state import set_control as _set_control
    await _set_control(run_id, "pause")
    await get_ledger().async_update_run_status(run_id, "paused")
    return {"run_id": run_id, "status": "paused"}


@router.post("/factory/runs/{run_id}/resume")
async def resume_factory_run(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Resume a paused pipeline run."""
    from aether_os.core.audit.ledger import get_ledger
    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    from aether_os.core.pipeline_state import set_control as _set_control
    await _set_control(run_id, "run")
    await get_ledger().async_update_run_status(run_id, "running")
    return {"run_id": run_id, "status": "running"}


@router.post("/factory/runs/{run_id}/restart")
async def restart_factory_run(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Restart a crashed/failed run from its last saved checkpoint.

    The pipeline reads checkpoint_data from the DB and resumes from the phase
    after the last successfully completed one.  Returns 409 if the run has no
    checkpoint or is not in a failed/cancelled state.
    """
    from aether_os.core.audit.ledger import get_ledger
    from aether_os.core.db import get_session_factory as _gsf_restart
    from aether_os.core.models import Run as _Run_restart
    from sqlalchemy import select as _sel_restart, update as _upd_restart
    from aether_os.orchestrator.factory_pipeline import get_factory as _get_factory_r

    org_id = user.get("org_id")
    async with _gsf_restart()() as _s_r:
        _run_r = (await _s_r.execute(
            _sel_restart(_Run_restart).where(
                _Run_restart.id == run_id,
                _Run_restart.org_id == org_id,
            )
        )).scalar_one_or_none()
    if not _run_r:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if _run_r.status not in ("failed", "cancelled", "error", "interrupted"):
        raise HTTPException(status_code=409, detail=f"Run is {_run_r.status}; only failed/cancelled/interrupted runs can be restarted")
    _ckpt = _run_r.checkpoint_data
    if not _ckpt or not isinstance(_ckpt, dict) or not _ckpt.get("last_completed_phase"):
        raise HTTPException(status_code=409, detail="No checkpoint saved for this run — use /rerun to start fresh")

    # Reset status so pipeline does not immediately exit
    async with _gsf_restart()() as _s_r2:
        await _s_r2.execute(
            _upd_restart(_Run_restart)
            .where(_Run_restart.id == run_id)
            .values(status="running")
        )
        await _s_r2.commit()

    raw_input = (_run_r.raw_input or _run_r.command or "").replace("factory: ", "")
    _factory_r = _get_factory_r()
    _bg_tasks_r = _get_background_tasks()

    async def _restart_bg():
        try:
            # Clear any stale cancel/pause signal before resuming
            from aether_os.core.pipeline_state import set_control as _sc_restart
            await _sc_restart(run_id, "run")
            await _factory_r.run(
                client_id=user.get("org_slug", "restart"),
                raw_input=raw_input,
                run_id=run_id,
                org_id=org_id,
            )
        except Exception as _exc_r:
            logger.error("Restart failed for run %s: %s", run_id, _exc_r)

    _t_r = asyncio.create_task(_restart_bg())
    _bg_tasks_r.add(_t_r)
    _t_r.add_done_callback(_bg_tasks_r.discard)

    resumed_after = _ckpt.get("last_completed_phase", "unknown")
    return {"run_id": run_id, "status": "running", "resumed_after": resumed_after}


@router.post("/factory/runs/{run_id}/cancel")
async def cancel_factory_run(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Cancel a running or paused pipeline run."""
    from aether_os.core.audit.ledger import get_ledger
    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    from aether_os.core.pipeline_state import set_control as _set_control
    await _set_control(run_id, "cancel")
    await get_ledger().async_update_run_status(run_id, "cancelled")
    return {"run_id": run_id, "status": "cancelled"}


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
    from sqlalchemy.dialects.postgresql import insert as _pg_insert
    from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
    _sf_pri = _gsf_pri()
    async with _sf_pri() as _sess_pri:
        existing = await _sess_pri.get(_RM_pri, run_id)
        if existing:
            existing.priority = req.priority
            existing.updated_at = time.time()
        else:
            _sess_pri.add(_RM_pri(run_id=run_id, priority=req.priority, updated_at=time.time()))
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
    from aether_os.core.audit.ledger import get_ledger as _get_ledger

    org_id = user.get("org_id")
    from aether_os.core.audit.ledger import get_ledger
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
                raise HTTPException(status_code=402, detail={"error": "trial_limit_reached", "upgrade_url": "/pricing"})

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
    from sqlalchemy import select as _sel_b, update as _upd_b
    branch_phase = req.get("branch_phase", "p04_backend")
    extra_input = req.get("extra_input", "")
    org_id = user.get("org_id")
    async with _gsf_b()() as _s:
        parent = (await _s.execute(_sel_b(_RunB).where(_RunB.id == run_id, _RunB.org_id == org_id))).scalar_one_or_none()
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
            started_at=__import__('time').time(),
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
    return {"run_id": new_run_id, "status": "started", "parent_run_id": run_id, "branch_phase": branch_phase}


@router.post("/factory/runs/{run_id}/sse-token")
async def get_sse_token(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, str]:
    """Exchange bearer JWT for a short-lived (30s) SSE-only token for this run."""
    import secrets
    from aether_os.core.rate_limiter import sse_token_set
    sse_tok = secrets.token_urlsafe(32)
    await sse_token_set(sse_tok, org_id=user["org_id"], run_id=run_id)
    return {"sse_token": sse_tok}


@router.get("/factory/runs/{run_id}/stream")
async def stream_run_events(
    run_id: str,
    request: Request,
    sse_token: Optional[str] = None,
    last_event_id: Optional[str] = None,
):
    """Server-Sent Events stream for live pipeline output.

    Auth: POST /factory/runs/{run_id}/sse-token first, then use the
    returned sse_token as a query param here. JWTs must never be passed
    in URLs (they land in nginx/proxy logs).

    Fix 21: Accepts Last-Event-ID header to resume from a specific position
    so reconnects do not replay all events from the beginning.
    """
    from fastapi.responses import StreamingResponse, Response
    from aether_os.core.audit.ledger import get_ledger
    from aether_os.core.rate_limiter import sse_token_pop

    if not sse_token:
        return Response(status_code=401, content="sse_token required — POST /factory/runs/{run_id}/sse-token first")

    entry = await sse_token_pop(sse_token)
    if not entry or entry.get("run_id") != run_id:
        return Response(status_code=401, content="SSE token invalid or expired")

    org_id = entry["org_id"]
    if not org_id:
        return Response(status_code=401, content="Invalid token")

    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        return Response(status_code=404, content="Run not found or access denied")

    # Fix 21: parse Last-Event-ID — browsers send this as a header on reconnect (HTML5 EventSource
    # spec). Also accept the query param as a fallback for non-browser clients.
    _last_seen = -1
    _header_lei = request.headers.get("Last-Event-ID") or request.headers.get("last-event-id")
    _raw_lei = _header_lei if _header_lei is not None else last_event_id
    if _raw_lei is not None:
        try:
            _last_seen = int(_raw_lei)
        except (ValueError, TypeError):
            _last_seen = -1

    async def event_generator():
        from aether_os.core.pipeline_state import get_redis, get_event_history, _local_history

        # Fix 21: replay only events after last_seen position
        history = await get_event_history(run_id)
        # Fix 22: check decisions table for spec_review_ready events before replaying
        _decided_ids: set = set()
        try:
            from aether_os.core.decisions.decision_engine import get_decision_engine as _gde
            _engine = _gde()
            _decisions = await _engine.list_for_run(run_id, status=None)
            _decided_ids = {
                d.id for d in _decisions
                if getattr(d, "status", None) in ("approved", "rejected")
            }
        except Exception:
            pass

        replay_start = _last_seen + 1
        for idx, past_event in enumerate(history[replay_start:], start=replay_start):
            # Fix 22: swap spec_review_ready for decision_already_made if already decided
            _etype = past_event.get("type", "")
            if _etype in ("spec_review_ready", "PhaseApprovalRequired"):
                _did = past_event.get("decision_id")
                if _did and _did in _decided_ids:
                    past_event = {**past_event, "type": "decision_already_made", "original_type": _etype}
            yield f"id: {idx}\ndata: {json.dumps(past_event)}\n\n"

        r = await get_redis()
        if r is None:
            # Redis unavailable — poll the in-process _local_history buffer.
            # The pipeline writes to _local_history when Redis is down, so we
            # tail it here rather than abandoning the stream.
            seen = len(history)
            _deadline = asyncio.get_event_loop().time() + 1800  # 30-min hard timeout
            while True:
                if asyncio.get_event_loop().time() > _deadline:
                    yield f"data: {json.dumps({'type': 'stream_timeout', 'message': 'SSE fallback stream timed out after 30 minutes'})}\n\n"
                    return
                buf = _local_history.get(run_id, [])
                for raw in buf[seen:]:
                    seen += 1
                    yield f"id: {seen - 1}\ndata: {raw}\n\n"
                    try:
                        if json.loads(raw).get("type") == "pipeline_complete":
                            return
                    except Exception:
                        pass
                await asyncio.sleep(0.5)
            return

        pubsub = r.pubsub()
        await pubsub.subscribe(f"pipeline:events:{run_id}")
        _live_idx = len(history)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    event = json.loads(message["data"])
                except Exception:
                    continue
                # Fix 22: also gate spec_review_ready on live events
                _etype = event.get("type", "")
                if _etype in ("spec_review_ready", "PhaseApprovalRequired"):
                    _did = event.get("decision_id")
                    if _did and _did in _decided_ids:
                        event = {**event, "type": "decision_already_made", "original_type": _etype}
                yield f"id: {_live_idx}\ndata: {json.dumps(event)}\n\n"
                _live_idx += 1
                if event.get("type") == "pipeline_complete":
                    break
        except Exception as _sse_exc:
            import logging as _log
            _log.getLogger(__name__).warning("SSE Redis pubsub error for run %s: %s", run_id, _sse_exc)
            yield f"data: {json.dumps({'type': 'stream_error', 'message': 'SSE connection lost; please reconnect'})}\n\n"
        finally:
            await pubsub.unsubscribe(f"pipeline:events:{run_id}")
            await pubsub.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/factory/runs/{run_id}/preview")
async def preview_run_html(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """Serve the generated index.html."""
    from fastapi.responses import HTMLResponse
    from aether_os.core.audit.ledger import get_ledger as _get_ledger

    org_id = user.get("org_id")
    run_detail = await _get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not run_detail:
        raise HTTPException(status_code=404, detail="Run not found")

    project_id = run_id
    if run_detail and "project_id" in run_detail:
        project_id = run_detail["project_id"]

    from aether_os.core.projects import get_project_manager as _get_pm
    root_dir = _get_pm().get_project_dir(project_id)

    # Walk looking for index.html
    for candidate in [
        root_dir / "p05_frontend" / "index.html",
        root_dir / "index.html",
    ]:
        if candidate.exists():
            return HTMLResponse(content=candidate.read_text(encoding="utf-8"))

    # Recursive search
    for html_file in root_dir.rglob("index.html"):
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))

    raise HTTPException(status_code=404, detail="No index.html found in run artifacts")


# ── Factory run file management ────────────────────────────────────────────────

@router.get("/factory/runs/{run_id}/files")
async def get_run_files(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Recursive file tree for a run's output directory."""
    from aether_os.core.projects import get_project_manager
    from aether_os.core.audit.ledger import get_ledger

    org_id = user.get("org_id")
    run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not run_detail:
        raise HTTPException(status_code=404, detail="Run not found")

    project_id = run_id
    if run_detail and "project_id" in run_detail:
         project_id = run_detail["project_id"]

    root_dir = get_project_manager().get_project_dir(project_id)

    if not root_dir.exists():
        return {"run_id": run_id, "tree": []}

    def build_tree(current_path: pathlib.Path, base_path: pathlib.Path) -> List[Dict]:
        items = []
        for item in sorted(current_path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
            if item.name.startswith("."):
                continue

            rel_path = str(item.relative_to(base_path))
            if item.is_dir():
                items.append({
                    "name": item.name,
                    "type": "directory",
                    "path": rel_path,
                    "children": build_tree(item, base_path)
                })
            else:
                items.append({
                    "name": item.name,
                    "type": "file",
                    "path": rel_path,
                    "size_bytes": item.stat().st_size,
                    "extension": item.suffix
                })
        return items

    return {
        "run_id": run_id,
        "tree": build_tree(root_dir, root_dir)
    }


@router.get("/factory/runs/{run_id}/file-content")
async def get_file_content(
    run_id: str,
    path: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Read file content."""
    from aether_os.core.projects import get_project_manager
    from aether_os.core.audit.ledger import get_ledger

    org_id = user.get("org_id")
    run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not run_detail:
        raise HTTPException(status_code=404, detail="Run not found")

    project_id = run_id
    if run_detail and "project_id" in run_detail:
         project_id = run_detail["project_id"]

    root_dir = get_project_manager().get_project_dir(project_id).resolve()
    # Sanitise path: strip leading slashes/dots to prevent absolute path injection
    safe_relative = pathlib.Path(path.lstrip("/")).resolve().relative_to(pathlib.Path("/").resolve()) if path.startswith("/") else pathlib.Path(path)
    file_path = (root_dir / safe_relative).resolve()

    # Proper boundary check: ensure resolved path is INSIDE root_dir (not just a prefix match)
    try:
        file_path.relative_to(root_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal detected")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    ext = file_path.suffix.lower()

    # Image check
    if ext in [".png", ".jpg", ".jpeg", ".gif", ".svg"]:
        return {
            "path": path,
            "type": "image",
            "message": "Image files cannot be previewed"
        }

    # Language mapping
    lang_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".sh": "bash",
        ".toml": "toml",
        ".html": "html",
        ".css": "css",
        ".diff": "diff"
    }
    language = lang_map.get(ext, "text")

    # Read and truncate if needed
    size = file_path.stat().st_size
    truncated = False
    content = ""

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            if size > 1_000_000:
                content = f.read(50_000)
                truncated = True
            else:
                content = f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {e}")

    return {
        "path": path,
        "content": content,
        "language": language,
        "size_bytes": size,
        "truncated": truncated,
        "type": "diff" if ext == ".diff" else "text"
    }


# ── FDE: File write, VS Code open, env vars, run-app ──────────────────────────

@router.patch("/factory/runs/{run_id}/file-content")
async def patch_file_content(
    run_id: str,
    body: FileWriteBody,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Write content to a file in the project directory."""
    if user.get("role") == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot write files")
    from aether_os.core.projects import get_project_manager
    from aether_os.core.audit.ledger import get_ledger

    org_id = user.get("org_id")
    run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not run_detail:
        raise HTTPException(status_code=404, detail="Run not found")

    project_id = run_id
    if run_detail and "project_id" in run_detail:
        project_id = run_detail["project_id"]

    root_dir = get_project_manager().get_project_dir(project_id).resolve()
    path = body.path
    safe_relative = pathlib.Path(path.lstrip("/")).resolve().relative_to(pathlib.Path("/").resolve()) if path.startswith("/") else pathlib.Path(path)
    file_path = (root_dir / safe_relative).resolve()

    try:
        file_path.relative_to(root_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal detected")

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(body.content, encoding="utf-8")
        
        # Post-write baseline update for Guardian
        try:
            from aether_os.core.guardian.threat_detector import get_threat_detector
            await get_threat_detector().update_baseline(file_path)
        except Exception as e:
            logger.warning("Guardian: failed to update baseline after file write: %s", e)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing file: {e}")

    return {"run_id": run_id, "path": path, "size": file_path.stat().st_size}


@router.post("/factory/runs/{run_id}/open-in-vscode")
async def open_in_vscode(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Open the project folder in VS Code on the local machine."""
    import subprocess as _sp
    from aether_os.core.projects import get_project_manager
    from aether_os.core.audit.ledger import get_ledger

    org_id = user.get("org_id")
    run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not run_detail:
        raise HTTPException(status_code=404, detail="Run not found")

    project_id = run_id
    if run_detail and "project_id" in run_detail:
        project_id = run_detail["project_id"]

    root_dir = get_project_manager().get_project_dir(project_id).resolve()

    try:
        _sp.run(["code", str(root_dir)], check=False, capture_output=True)
        return {"opened": True, "path": str(root_dir)}
    except FileNotFoundError:
        return {"opened": False, "error": "VS Code CLI (code) not found in PATH"}


@router.get("/factory/runs/{run_id}/envvars")
async def get_envvars(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Read the .env (or .env.example) file from the project root."""
    from aether_os.core.projects import get_project_manager
    from aether_os.core.audit.ledger import get_ledger

    org_id = user.get("org_id")
    run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not run_detail:
        raise HTTPException(status_code=404, detail="Run not found")

    project_id = run_id
    if run_detail and "project_id" in run_detail:
        project_id = run_detail["project_id"]

    root_dir = get_project_manager().get_project_dir(project_id).resolve()

    env_path = root_dir / ".env"
    source = ".env"
    if not env_path.exists():
        # Check root .env.example, then generated backend subdirectory
        for _candidate, _src in [
            (root_dir / ".env.example", ".env.example"),
            (root_dir / "p04_backend" / "backend_codegen" / ".env", ".env"),
            (root_dir / "p04_backend" / "backend_codegen" / ".env.example", ".env.example"),
        ]:
            if _candidate.exists():
                env_path = _candidate
                source = _src
                break

    vars_list: List[Dict[str, str]] = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                k, _, v = stripped.partition("=")
                vars_list.append({"key": k.strip(), "value": v.strip()})

    return {"run_id": run_id, "vars": vars_list, "source": source}


@router.patch("/factory/runs/{run_id}/envvars")
async def patch_envvars(
    run_id: str,
    body: EnvVarsBody,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Write a .env file in the project root from the given key-value pairs."""
    if user.get("role") == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot write env vars")
    from aether_os.core.projects import get_project_manager
    from aether_os.core.audit.ledger import get_ledger

    org_id = user.get("org_id")
    run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not run_detail:
        raise HTTPException(status_code=404, detail="Run not found")

    project_id = run_id
    if run_detail and "project_id" in run_detail:
        project_id = run_detail["project_id"]

    root_dir = get_project_manager().get_project_dir(project_id).resolve()
    env_path = root_dir / ".env"

    lines = [f"{item.key}={item.value}" for item in body.vars]
    try:
        fd, tmp_name = tempfile.mkstemp(dir=env_path.parent, prefix=".env.tmp.")
        try:
            with os.fdopen(fd, 'w', encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(tmp_name, env_path)
        except Exception:
            os.unlink(tmp_name)
            raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing .env: {e}")

    return {"run_id": run_id, "written": len(body.vars)}


# Maps run_id → project root dir (for proxy to find static frontend build)
_APP_DIRS: Dict[str, str] = {}

def get_active_preview_dir() -> Optional[str]:
    """Return the project dir of the most recently started app preview."""
    return _APP_DIRS.get("__current__")


def _free_port() -> int:
    """Return an unused TCP port on localhost.

    For concurrent-safe allocation use core.services.run_app_service.acquire_free_port().
    """
    from aether_os.core.services.run_app_service import _free_port as _svc_free_port
    return _svc_free_port()


def _get_app_ports() -> Dict[str, int]:
    from aether_os.core.app_state import get_all_ports
    return get_all_ports()


@router.post("/factory/runs/{run_id}/run-app")
async def start_run_app(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Start the generated app with uvicorn. Installs deps and builds frontend."""
    import subprocess as _sp
    import shutil as _sh
    from aether_os.core.projects import get_project_manager
    from aether_os.core.audit.ledger import get_ledger
    from pathlib import Path as _P

    _run_procs = _get_app_procs()
    _run_ports = _get_app_ports()
    existing = _run_procs.get(run_id)
    if existing is not None and existing.poll() is None:
        return {"status": "already_running", "pid": existing.pid,
                "port": _run_ports.get(run_id, int(os.environ.get("RUN_APP_PORT", "8001")))}

    org_id = user.get("org_id")
    run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not run_detail:
        raise HTTPException(status_code=404, detail="Run not found")

    project_id = run_id
    if run_detail and "project_id" in run_detail:
        project_id = run_detail["project_id"]

    root_dir = get_project_manager().get_project_dir(project_id).resolve()
    from aether_os.core.services.run_app_service import acquire_free_port
    port = await acquire_free_port()

    # ── Locate backend entry point ────────────────────────────────────────────
    # Prefer the merged/scaffolded version (p03 wrote the full app); fall back to p04 codegen.
    backend_dir: Optional[_P] = None
    candidates = [
        # p04_backend/backend_codegen is preferred — self-contained generated code with no relative imports
        # p03_scaffolding comes second — may reference routers that don't exist in scaffold
        root_dir / "p04_backend" / "backend_codegen",
        root_dir / "p03_scaffolding",   # may contain "ProjectName/" subdir
    ]
    for cand in candidates:
        if cand.is_dir():
            # p03 may have a single subdirectory (the project name)
            subdirs = [d for d in cand.iterdir() if d.is_dir() and (d / "src" / "main.py").exists()]
            if subdirs:
                backend_dir = subdirs[0]
                break
            if (cand / "src" / "main.py").exists():
                backend_dir = cand
                break

    if not backend_dir:
        raise HTTPException(status_code=422, detail="Could not locate backend src/main.py in generated project.")

    import sys as _sys
    import os as _os
    log_path = root_dir / "run_app.log"

    # ── Install Python dependencies ───────────────────────────────────────────
    # Always install aiosqlite so the SQLite preview swap works without pg deps.
    _sp.run(
        [_sys.executable, "-m", "pip", "install", "aiosqlite", "httpx", "-q", "--no-warn-script-location"],
        capture_output=True, timeout=60
    )
    req_file = backend_dir / "requirements.txt"
    if req_file.exists():
        # Strip PostgreSQL drivers from requirements — the preview runs on SQLite.
        _req_lines = req_file.read_text().splitlines()
        _lite_reqs = [
            ln for ln in _req_lines
            if not any(pkg in ln.lower() for pkg in ("psycopg2", "asyncpg", "pg8000"))
        ]
        _lite_req_path = root_dir / "_preview_requirements.txt"
        _lite_req_path.write_text("\n".join(_lite_reqs))
        with open(log_path, "w") as _lf:
            _lf.write(f"[AetherOS] Installing backend deps (SQLite preview mode)\n")
        _sp.run(
            [_sys.executable, "-m", "pip", "install", "-r", str(_lite_req_path), "-q", "--no-warn-script-location"],
            capture_output=True, timeout=120
        )

    # ── Locate frontend (p05 writes to p05_frontend/frontend/) ───────────────
    _frontend_candidates = [
        root_dir / "p05_frontend" / "frontend",
        root_dir / "frontend",
    ]
    frontend_dir = next((d for d in _frontend_candidates if (d / "package.json").exists()), None)
    frontend_dist = (frontend_dir / "dist") if frontend_dir else None

    # ── Build React frontend (if Node.js is available) ────────────────────────
    node_bin = _sh.which("node")
    npm_bin = _sh.which("npm")
    if node_bin and npm_bin and frontend_dir and frontend_dir.is_dir():
        # Patch vite.config + env + router BEFORE building so asset URLs and API calls
        # work correctly when the app is served at /app-preview/ via the gateway proxy.
        import re as _re_cfg
        for _cfg_name in ("vite.config.ts", "vite.config.js"):
            _cfg_path = frontend_dir / _cfg_name
            if _cfg_path.exists():
                _cfg = _cfg_path.read_text()
                if "base:" not in _cfg and "basePath" not in _cfg:
                    _cfg = _cfg.replace(
                        "export default defineConfig({",
                        "export default defineConfig({\n  base: '/app-preview/',"
                    )
                    _cfg_path.write_text(_cfg)
                break
        # Write .env.production: VITE_API_URL points to the gateway proxy path + /api prefix.
        # Always overwrite — the pipeline build may have used a different (wrong) URL.
        _env_prod = frontend_dir / ".env.production"
        _correct_env = "VITE_API_URL=/app-preview/api\n"
        _env_changed = not _env_prod.exists() or _env_prod.read_text() != _correct_env
        _env_prod.write_text(_correct_env)

        # Patch src/lib/api.ts: replace any hardcoded /api base URL with /app-preview/api.
        # LLM-generated API clients often use axios.create({baseURL:'/api'}) instead of the env var.
        for _api_src in ("src/lib/api.ts", "src/lib/api.tsx", "src/api.ts", "src/api.js"):
            _api_path = frontend_dir / _api_src
            if _api_path.exists():
                _api_code = _api_path.read_text()
                _patched = False
                for _wrong in ("baseURL: '/api'", 'baseURL: "/api"', "baseURL:'/api'", 'baseURL:"/api"'):
                    if _wrong in _api_code:
                        _api_code = _api_code.replace(_wrong, "baseURL: '/app-preview/api'")
                        _patched = True
                if _patched:
                    _api_path.write_text(_api_code)
                    _env_changed = True  # source changed → force rebuild
                break

        # Patch TanStack Router / React Router basename so routes resolve under /app-preview/
        for _src_name in ("src/App.tsx", "src/App.jsx", "src/main.tsx", "src/main.jsx"):
            _src_path = frontend_dir / _src_name
            if _src_path.exists():
                _src = _src_path.read_text()
                if "createRouter" in _src and "basepath" not in _src and "basePath" not in _src:
                    _src = _src.replace(
                        "createRouter({ routeTree })",
                        "createRouter({ routeTree, basepath: '/app-preview' })"
                    )
                    _src_path.write_text(_src)
                elif "BrowserRouter" in _src and "basename" not in _src:
                    _src = _src.replace("BrowserRouter>", "BrowserRouter basename='/app-preview'>")
                    _src = _src.replace("BrowserRouter />", "BrowserRouter basename='/app-preview' />")
                    _src_path.write_text(_src)

        # Rebuild if dist doesn't exist OR if env/source changed (ensures correct API URL).
        _dist_already_built = (not _env_changed and frontend_dist
                               and frontend_dist.is_dir() and any(frontend_dist.iterdir()))
        if not _dist_already_built:
            with open(log_path, "a") as _lf:
                _lf.write(f"[AetherOS] Building React frontend from {frontend_dir}...\n")
            _npm_cache = _os.path.expanduser("~/.aether_os/npm_cache")
            _npm_install_r = _sp.run(
                [npm_bin, "install", "--silent", "--cache", _npm_cache],
                cwd=str(frontend_dir), capture_output=True, timeout=300,
            )
            if _npm_install_r.returncode != 0:
                _npm_err = (_npm_install_r.stderr or b"").decode(errors="replace")[-400:]
                with open(log_path, "a") as _lf:
                    _lf.write(f"[AetherOS] npm install failed (rc={_npm_install_r.returncode}):\n{_npm_err}\n")

            # Patch tsconfig.json to suppress type errors in generated code.
            # Generated TypeScript often has minor type issues that block tsc but not vite.
            import json as _json_ts
            for _ts_name in ("tsconfig.json", "tsconfig.app.json"):
                _ts_path = frontend_dir / _ts_name
                if _ts_path.exists():
                    try:
                        _ts = _json_ts.loads(_ts_path.read_text())
                        _co = _ts.setdefault("compilerOptions", {})
                        _co.update({
                            "skipLibCheck": True,
                            "strict": False,
                            "noImplicitAny": False,
                            "allowSyntheticDefaultImports": True,
                            "noUnusedLocals": False,
                            "noUnusedParameters": False,
                        })
                        _ts_path.write_text(_json_ts.dumps(_ts, indent=2))
                    except Exception:
                        pass

            # Patch vite.config: swap plugin-react-swc → plugin-react if swc not installed.
            # Generated code often uses -swc but the preview environment may not have it.
            for _vc_name in ("vite.config.ts", "vite.config.js"):
                _vc_path = frontend_dir / _vc_name
                if _vc_path.exists():
                    _vc = _vc_path.read_text()
                    if "plugin-react-swc" in _vc:
                        _swc_installed = (frontend_dir / "node_modules" / "@vitejs" / "plugin-react-swc").is_dir()
                        if not _swc_installed:
                            _vc = _vc.replace("@vitejs/plugin-react-swc", "@vitejs/plugin-react")
                            _vc_path.write_text(_vc)
                    break

            # Try vite build (skips tsc type checking by default).
            # NODE_OPTIONS caps the V8 heap; ESBUILD_WORKER_THREADS=false disables
            # Go multi-threading in the esbuild subprocess, cutting peak RAM ~40%.
            _npx_bin = _sh.which("npx") or "npx"
            _node_env = {
                **_os.environ,
                "NODE_OPTIONS": "--max-old-space-size=384",
                "ESBUILD_WORKER_THREADS": "false",
            }
            _vite_result = _sp.run(
                [_npx_bin, "vite", "build"],
                cwd=str(frontend_dir), capture_output=True, timeout=300,
                env=_node_env,
            )
            if _vite_result.returncode != 0:
                _err = (_vite_result.stderr or b"").decode(errors="replace")[-800:]
                with open(log_path, "a") as _lf:
                    _lf.write(f"[AetherOS] Vite build failed (rc={_vite_result.returncode}):\n{_err}\n")
                # Second attempt: ensure @vitejs/plugin-react is installed then retry.
                # OOM detection: also catches esbuild Go-subprocess pipe crash (rc=1 +
                # "responseCallbacks" in stderr) which the kernel kills with SIGKILL before
                # the Node.js wrapper can propagate -9/137 to the parent subprocess.
                _oom = (
                    _vite_result.returncode in (-9, 137)
                    or "Killed" in _err
                    or "responseCallbacks" in _err
                    or "write EPIPE" in _err
                    or "read ECONNRESET" in _err
                )
                _node_env2 = {
                    **_node_env,
                    "NODE_OPTIONS": "--max-old-space-size=192",
                    "ESBUILD_WORKER_THREADS": "false",
                } if _oom else _node_env
                _sp.run(
                    [npm_bin, "install", "--save-dev", "@vitejs/plugin-react", "--silent",
                     "--cache", _npm_cache],
                    cwd=str(frontend_dir), capture_output=True, timeout=120,
                )
                # On OOM-style failure, disable minification to cut esbuild peak RAM by ~40%.
                if _oom:
                    for _vc_name2 in ("vite.config.ts", "vite.config.js"):
                        _vc_path2 = frontend_dir / _vc_name2
                        if _vc_path2.exists():
                            _vc2 = _vc_path2.read_text()
                            if "minify" not in _vc2 and "build:" not in _vc2:
                                _vc2 = _vc2.replace(
                                    "export default defineConfig({",
                                    "export default defineConfig({\n  build: { minify: false, chunkSizeWarningLimit: 4000 },",
                                )
                                _vc_path2.write_text(_vc2)
                            break
                _vite_result2 = _sp.run(
                    [_npx_bin, "vite", "build"],
                    cwd=str(frontend_dir), capture_output=True, timeout=300,
                    env=_node_env2,
                )
                if _vite_result2.returncode != 0:
                    _err2 = (_vite_result2.stderr or b"").decode(errors="replace")[-400:]
                    with open(log_path, "a") as _lf:
                        _lf.write(f"[AetherOS] Frontend build failed after retry:\n{_err2}\n[AetherOS] Using API-explorer fallback\n")

            if frontend_dist and frontend_dist.is_dir() and any(frontend_dist.iterdir()):
                with open(log_path, "a") as _lf:
                    _lf.write(f"[AetherOS] Frontend built → {frontend_dist}\n")
            else:
                # Build failed: synthesise a lightweight API-explorer page so the user
                # sees a real UI instead of a blank page or Swagger redirect.
                frontend_dist = root_dir / "_preview_ui"
                frontend_dist.mkdir(exist_ok=True)
                _project_label = (run_detail.get("project_name") or f"project-{run_id[:8]}").replace("'", "\\'")
                (frontend_dist / "index.html").write_text(f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_project_label}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;padding:2rem}}
  h1{{font-size:1.5rem;font-weight:700;color:#f1f5f9;margin-bottom:.25rem}}
  .badge{{display:inline-block;padding:.2rem .6rem;border-radius:9999px;font-size:.7rem;font-weight:600;background:#1e3a5f;color:#60a5fa;margin-bottom:1.5rem}}
  .card{{background:#1e293b;border:1px solid #334155;border-radius:.75rem;padding:1.25rem;margin-bottom:1rem}}
  .card h2{{font-size:.85rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.75rem}}
  .cred-row{{display:flex;gap:.5rem;align-items:center;margin-bottom:.4rem;font-size:.875rem}}
  .label{{color:#64748b;width:5rem;flex-shrink:0}}
  code{{background:#0f172a;color:#34d399;padding:.15rem .4rem;border-radius:.3rem;font-size:.8rem;font-family:monospace}}
  .btn{{display:inline-flex;align-items:center;gap:.4rem;padding:.5rem 1rem;border-radius:.5rem;font-size:.8rem;font-weight:600;text-decoration:none;transition:opacity .15s}}
  .btn-primary{{background:#6366f1;color:#fff}}.btn-primary:hover{{opacity:.85}}
  .btn-outline{{background:transparent;border:1px solid #334155;color:#94a3b8}}.btn-outline:hover{{color:#f1f5f9;border-color:#6366f1}}
  .btn-row{{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.75rem}}
  #endpoints{{font-size:.8rem;line-height:1.8}}
  .method{{display:inline-block;width:3.5rem;text-align:center;border-radius:.25rem;padding:.05rem .3rem;font-size:.7rem;font-weight:700;margin-right:.4rem}}
  .GET{{background:#065f46;color:#6ee7b7}}.POST{{background:#1e3a5f;color:#93c5fd}}
  .PUT,.PATCH{{background:#44310a;color:#fcd34d}}.DELETE{{background:#4c1d24;color:#fca5a5}}
  #status{{margin-top:.5rem;font-size:.75rem;color:#64748b}}
</style>
</head>
<body>
<h1>{_project_label}</h1>
<div class="badge">AetherOS Generated App · Preview Mode</div>

<div class="card">
  <h2>Demo Credentials</h2>
  <div class="cred-row"><span class="label">Email</span><code id="email">loading…</code></div>
  <div class="cred-row"><span class="label">Password</span><code id="password">loading…</code></div>
  <div class="btn-row">
    <a href="/app-preview/docs" target="_blank" class="btn btn-primary">📖 API Docs (Swagger)</a>
    <a href="/app-preview/openapi.json" target="_blank" class="btn btn-outline">JSON Schema</a>
  </div>
</div>

<div class="card">
  <h2>API Endpoints</h2>
  <div id="endpoints"><span style="color:#475569">Loading…</span></div>
  <div id="status"></div>
</div>

<script>
const base='/app-preview';
fetch('/api/factory/runs/{run_id}/preview-credentials',{{headers:{{'Authorization':'Bearer '+(localStorage.getItem('aether_token')||'')}}}})
  .then(r=>r.ok?r.json():null).then(d=>{{
    if(d){{document.getElementById('email').textContent=d.email||'admin@example.com';document.getElementById('password').textContent=d.password||'Admin1234!';}}
  }}).catch(()=>{{}});

fetch(base+'/openapi.json').then(r=>r.json()).then(spec=>{{
  const paths=Object.entries(spec.paths||{{}});
  const html=paths.slice(0,40).flatMap(([path,methods])=>
    Object.entries(methods).filter(([m])=>['get','post','put','patch','delete'].includes(m)).map(([method,op])=>
      `<div><span class="method ${{method.toUpperCase()}}">${{method.toUpperCase()}}</span><code>${{path}}</code> <span style="color:#475569">${{op.summary||''}}</span></div>`
    )
  ).join('');
  document.getElementById('endpoints').innerHTML=html||'<span style="color:#475569">No endpoints found</span>';
  document.getElementById('status').textContent=`${{paths.length}} endpoint group(s) available`;
}}).catch(()=>{{document.getElementById('endpoints').textContent='Could not load API schema — ensure the backend is running.';}});
</script>
</body></html>""")
                with open(log_path, "a") as _lf:
                    _lf.write(f"[AetherOS] Using API-explorer fallback UI at {frontend_dist}\n")
        else:
            with open(log_path, "a") as _lf:
                _lf.write(f"[AetherOS] Skipping frontend rebuild — dist already exists\n")

    # ── Patch main.py: fix common generation bugs + SQLite swap + frontend ───
    main_py = backend_dir / "src" / "main.py"
    if main_py.exists():
        import re as _re
        content = main_py.read_text()

        # Fix: typing.AsyncSession → AsyncSession (sqlalchemy bug in codegen)
        content = content.replace("class_=typing.AsyncSession", "class_=AsyncSession")

        # Fix: `import timezone` is not a valid stdlib import — timezone is a class inside datetime.
        # Remove the bare import and ensure `from datetime import ..., timezone` is present.
        if _re.search(r'^import timezone\b', content, _re.MULTILINE):
            content = _re.sub(r'^import timezone\b[^\n]*\n?', '', content, flags=_re.MULTILINE)
            if "from datetime import" in content:
                content = _re.sub(
                    r'from datetime import ([^\n]+)',
                    lambda m: m.group(0) if "timezone" in m.group(1)
                    else m.group(0).rstrip() + ", timezone",
                    content, count=1,
                )
            else:
                content = "from datetime import timezone\n" + content

        # Fix: add missing SQLAlchemy column type imports (Float, JSON, ARRAY, etc.)
        _sa_import_line = _re.search(
            r'^from sqlalchemy import ([^\n]+)', content, _re.MULTILINE
        )
        if _sa_import_line:
            _existing = _sa_import_line.group(1)
            _needed = ["Float", "JSON", "BigInteger", "Numeric", "LargeBinary", "UniqueConstraint"]
            _missing = [t for t in _needed if t not in _existing]
            if _missing:
                content = content.replace(
                    _sa_import_line.group(0),
                    _sa_import_line.group(0) + ", " + ", ".join(_missing)
                )

        # Fix: serve the frontend (Vite dist or _preview_ui fallback) from GET /.
        # Check frontend_dist first, then _preview_ui from a prior run or current run.
        _effective_dist = frontend_dist if (frontend_dist and frontend_dist.is_dir()) else None
        if _effective_dist is None:
            _preview_ui_fallback = root_dir / "_preview_ui"
            if (_preview_ui_fallback / "index.html").exists():
                _effective_dist = _preview_ui_fallback
        _dist_str = str(_effective_dist).replace("\\", "/") if _effective_dist else ""
        _will_add_spa = bool(_dist_str)
        with open(log_path, "a") as _lf:
            _lf.write(f"[AetherOS] main.py patch: _will_add_spa={_will_add_spa}, _dist_str={_dist_str!r}\n")
        if _will_add_spa:
            # Remove any existing GET "/" handler before appending the new one (idempotent).
            content = _re.sub(
                r'\n@app\.get\(["\']\/["\'][^)]*\)\n(?:async )?def [^\n]+\n(?:    [^\n]+\n)*',
                '\n',
                content,
            )
            # Add SPA root + catch-all so the frontend loads at / and all sub-paths.
            # Need two routes: GET / (Starlette's {path:path} doesn't match empty path)
            # and GET /{path:path} for all other paths.
            content += f"""

# AetherOS: serve the Vite-built frontend for all non-API paths (including root)
import pathlib as _spa_pathlib
_FRONTEND_DIST = _spa_pathlib.Path(r"{_dist_str}")

from fastapi.responses import FileResponse as _SpaFileResponse

@app.get("/", include_in_schema=False)
def _spa_root():
    return _SpaFileResponse(str(_FRONTEND_DIST / "index.html"))

@app.get("/{{path:path}}", include_in_schema=False)
def _spa_catchall(path: str = ""):
    _f = _FRONTEND_DIST / path
    if _f.is_file():
        return _SpaFileResponse(str(_f))
    return _SpaFileResponse(str(_FRONTEND_DIST / "index.html"))
"""
        else:
            # No frontend at all: add GET / → /docs redirect if not already present.
            # Generated main.py typically has no GET / handler, so regex-replace is a no-op;
            # always ADD the route instead.
            if not _re.search(r'@app\.get\(["\']\/["\']', content):
                content += (
                    '\n\n@app.get("/", include_in_schema=False)\n'
                    'def _root_redirect():\n'
                    '    from fastapi.responses import RedirectResponse\n'
                    '    return RedirectResponse(url="/docs")\n'
                )

        # Fix: LLM sometimes generates routes before `app = FastAPI()` — prepend boilerplate
        if _re.search(r'^@app\.', content, _re.MULTILINE) and not _re.search(
            r'^(?:app|application)\s*=\s*FastAPI\s*\(', content, _re.MULTILINE
        ):
            _boilerplate = (
                "from fastapi import FastAPI, HTTPException, Depends\n"
                "from fastapi.middleware.cors import CORSMiddleware\n"
                "import os as _os, uuid as _uuid, sqlite3 as _sqlite3\n"
                "from datetime import datetime as _dt\n"
                "app = FastAPI(title='Generated App', version='1.0.0')\n"
                "app.add_middleware(CORSMiddleware, allow_origins=['*'], "
                "allow_credentials=True, allow_methods=['*'], allow_headers=['*'])\n"
                "db = {}\n\n"
            )
            content = _boilerplate + content

        main_py.write_text(content)

        # FIX 4: Create run_preview.py instead of patching main.py
        run_preview_py = root_dir / "run_preview.py"
        _dist_str = str(frontend_dist).replace("\\", "/") if frontend_dist and frontend_dist.is_dir() else ""
        
        # Use relative paths for portability on the VPS filesystem
        preview_content = textwrap.dedent(f"""\
            \"\"\"AetherOS run-preview entrypoint — VPS only, not distributed.\"\"\"
            import os
            import pathlib
            import sys

            _PROJECT_DIR = pathlib.Path(__file__).parent
            # Add src to sys.path so 'import models', etc. works
            sys.path.insert(0, str(_PROJECT_DIR / "src"))

            _PREVIEW_DB = _PROJECT_DIR / "preview.db"
            _DIST = _PROJECT_DIR / "p05_frontend" / "frontend" / "dist"

            os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{{_PREVIEW_DB}}")
            os.environ.setdefault("SECRET_KEY", "aetheros-preview-secret-not-for-production")

            # Import the real app after setting env vars
            from main import app  # noqa: E402

            if _DIST.is_dir():
                from fastapi.staticfiles import StaticFiles
                from fastapi.responses import FileResponse
                from fastapi import HTTPException

                @app.get("/{{path:path}}", include_in_schema=False)
                def _spa(path: str = ""):
                    if path.startswith("api/"):
                        raise HTTPException(status_code=404, detail="Not found")
                    f = _DIST / path
                    return FileResponse(str(f) if f.is_file() else str(_DIST / "index.html"))
            
            if __name__ == "__main__":
                import uvicorn
                uvicorn.run(app, host="0.0.0.0", port=8000)
        """)
        run_preview_py.write_text(preview_content)

    # ── Patch models.py: fix duplicate keyword arguments in Column() calls ─────
    # LLM sometimes emits `Column(Boolean, default=True, ..., default=True)`.
    # Python 3.10+ raises SyntaxError on repeated kwargs, crashing the app.
    _models_py = backend_dir / "src" / "models.py"
    if _models_py.exists():
        import re as _re_m
        _m_src = _models_py.read_text()
        _m_lines = _m_src.splitlines()
        _m_out = []
        for _line in _m_lines:
            if "Column(" in _line:
                _seen_kw: set = set()
                def _drop_dup(m: "_re_m.Match") -> str:
                    k = m.group(1)
                    if k in _seen_kw:
                        return ""
                    _seen_kw.add(k)
                    return m.group(0)
                _line = _re_m.sub(r",\s*(\w+)=[^,)]+", _drop_dup, _line)
            _m_out.append(_line)
        _m_fixed = "\n".join(_m_out)
        if _m_fixed != _m_src:
            _models_py.write_text(_m_fixed)

    # ── Patch models.py: make FK columns nullable so preview inserts work ──────
    # LLM often emits nullable=False on ForeignKey columns. Without data in the
    # related tables the NOT NULL constraint fires on every insert in preview.
    if _models_py.exists():
        import re as _re_fk
        _fk_src = _models_py.read_text()
        _fk_lines = []
        for _ln in _fk_src.splitlines():
            if "ForeignKey" in _ln and "nullable=False" in _ln:
                _ln = _ln.replace("nullable=False", "nullable=True")
            _fk_lines.append(_ln)
        _fk_fixed = "\n".join(_fk_lines)
        if _fk_fixed != _fk_src:
            _models_py.write_text(_fk_fixed)

    # ── Patch schemas.py: make FK/bool/numeric fields optional with defaults ───
    # LLM emits required fields for FKs and booleans. Preview forms omit FK
    # dropdowns (no related data), causing 422 on every create. Make optional.
    # All regexes use negative lookaheads so re-running is idempotent.
    _schemas_py = backend_dir / "src" / "schemas.py"
    if _schemas_py.exists():
        import re as _re_s
        _s_src = _schemas_py.read_text()
        _s_src = _re_s.sub(r"(\n    (?:created_by|workspace_id|org_id|agent_id|member_id|organization_id|user_id)): int(?! =)", r"\1: Optional[int] = None", _s_src)
        _s_src = _re_s.sub(r"(\n    is_active): bool(?! =)", r"\1: bool = True", _s_src)
        _s_src = _re_s.sub(r"(\n    temperature): float(?! =)", r"\1: float = 0.7", _s_src)
        _s_src = _re_s.sub(r"(\n    max_tokens): int(?! =)", r"\1: int = 4096", _s_src)
        _s_src = _re_s.sub(r"(\n    tools_json): str(?! =)", r"\1: Optional[str] = None", _s_src)
        _schemas_py.write_text(_s_src)

    # ── Patch crud.py: replace getattr(user, 'role') with user.get('role') ─────
    # get_current_user returns a dict; getattr on a dict always returns None,
    # making every role check fail with 403. Also remove inconsistent per-entity
    # role lists that block the owner from accessing their own data.
    _crud_py = backend_dir / "src" / "routers" / "crud.py"
    if _crud_py.exists():
        import re as _re_c
        _c_src = _crud_py.read_text()
        _c_src = _c_src.replace('getattr(current_user, "role", None)', 'current_user.get("role")')
        _c_src = _c_src.replace("getattr(current_user, 'role', None)", 'current_user.get("role")')
        # Remove all role-gate lines (inconsistent role lists cause 403 for owner)
        _c_src = _re_c.sub(
            r"    if current_user\.get\(\"role\"\) not in \[.*?\]:\n        raise HTTPException\(status_code=403.*?\)\n",
            "", _c_src
        )
        _crud_py.write_text(_c_src)

    # ── Patch crud.py: add /api prefix to entity routers in main.py ─────────
    # LLM registers entity routers without prefix, but frontend baseURL = /api.
    # Patch the loop that registers all_routers to add prefix="/api".
    _main_py_crud = backend_dir / "src" / "main.py"
    if _main_py_crud.exists():
        _mp = _main_py_crud.read_text()
        if "for _router in all_routers:" in _mp and 'prefix="/api"' not in _mp:
            _mp = _mp.replace(
                "    app.include_router(_router)",
                '    app.include_router(_router, prefix="/api")'
            )
            _main_py_crud.write_text(_mp)

    # ── Patch react-router-dom → @tanstack/react-router in frontend pages ─────
    # LLM sometimes imports Link/useNavigate from react-router-dom while the
    # template uses @tanstack/react-router. Swap imports to avoid null context.
    _fe_src_dir = frontend_dir / "src" if frontend_dir else None
    if _fe_src_dir and _fe_src_dir.is_dir():
        import subprocess as _sp_rrd
        for _tsx in _fe_src_dir.rglob("*.tsx"):
            _tsx_src = _tsx.read_text()
            if "react-router-dom" in _tsx_src:
                _tsx_src = _tsx_src.replace(
                    "from 'react-router-dom'", "from '@tanstack/react-router'"
                ).replace(
                    'from "react-router-dom"', 'from "@tanstack/react-router"'
                )
                _tsx.write_text(_tsx_src)

    # ── Patch auth.py: replace passlib CryptContext with direct bcrypt ───────
    # passlib's bcrypt backend throws AttributeError on bcrypt >= 4.0 (missing __about__).
    # Replace get_password_hash / verify_password with direct bcrypt calls to avoid this.
    _auth_py = backend_dir / "src" / "auth.py"
    if _auth_py.exists():
        _auth = _auth_py.read_text()
        if "AetherOS: bcrypt direct" not in _auth and "CryptContext" in _auth:
            _bcrypt_patch = (
                "\n# AetherOS: bcrypt direct — passlib CryptContext incompatible with bcrypt >= 4.x\n"
                "try:\n"
                "    import bcrypt as _bcrypt_mod\n"
                "    def get_password_hash(pw: str) -> str:\n"
                "        return _bcrypt_mod.hashpw(pw.encode(), _bcrypt_mod.gensalt()).decode()\n"
                "    def verify_password(plain: str, hashed: str) -> bool:\n"
                "        try: return _bcrypt_mod.checkpw(plain.encode(), hashed.encode())\n"
                "        except Exception: return False\n"
                "except ImportError:\n"
                "    pass  # fall back to passlib\n"
            )
            _auth_py.write_text(_auth + _bcrypt_patch)

    # ── Patch seed.py: enforce predictable demo password for preview ──────────
    _PREVIEW_PASSWORD = "Admin1234!"
    _preview_email = "admin@example.com"
    _seed_py = backend_dir / "src" / "seed.py"
    if _seed_py.exists():
        import re as _re_seed
        _seed = _seed_py.read_text()
        # Extract admin email if present
        _email_m = _re_seed.search(r'email\s*=\s*["\']([^"\']+@[^"\']+)["\']', _seed)
        if _email_m:
            _preview_email = _email_m.group(1)
        # Replace any hardcoded password with the known preview password
        _seed_patched = _re_seed.sub(
            r'(_ADMIN_PASSWORD\s*=\s*)["\'][^"\']*["\']',
            f'\\1"{_PREVIEW_PASSWORD}"',
            _seed,
        )
        # Also patch get_password_hash(os.environ.get(...)) style
        _seed_patched = _re_seed.sub(
            r'get_password_hash\s*\(\s*os\.environ\.get\s*\([^)]+\)\s*\)',
            f'get_password_hash("{_PREVIEW_PASSWORD}")',
            _seed_patched,
        )
        if _seed_patched != _seed:
            _seed_py.write_text(_seed_patched)
    # Write preview_credentials.json so the UI can display them
    import json as _json
    _creds_path = root_dir / "preview_credentials.json"
    _creds_path.write_text(_json.dumps({
        "email": _preview_email,
        "password": _PREVIEW_PASSWORD,
        "note": "Demo credentials for the AetherOS preview — change before production",
    }))
    with open(log_path, "a") as _lf:
        _lf.write(f"[AetherOS] Preview credentials: {_preview_email} / {_PREVIEW_PASSWORD}\n")

    # ── Start uvicorn (with crash-detect fallback to frontend-only server) ──────
    _env = {**os.environ}
    _env["DATABASE_URL"] = f"sqlite+aiosqlite:///{root_dir}/preview.db"
    # Ensure generated app can import its own modules by flat name (e.g. from database import ...)
    _env["PYTHONPATH"] = str(backend_dir / "src") + ":" + _env.get("PYTHONPATH", "")

    # ── Run Alembic migrations before starting (best-effort) ─────────────────
    _alembic_ini = backend_dir / "alembic.ini"
    if _alembic_ini.exists():
        with open(log_path, "a") as _lf:
            _lf.write("[AetherOS] Running alembic upgrade head...\n")
        _alembic_result = _sp.run(
            [_sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(backend_dir),
            capture_output=True,
            timeout=60,
            env=_env,
        )
        with open(log_path, "a") as _lf:
            if _alembic_result.returncode == 0:
                _lf.write("[AetherOS] Alembic migrations applied successfully.\n")
            else:
                _err = (_alembic_result.stderr or b"").decode(errors="replace")[-400:]
                _lf.write(f"[AetherOS] Alembic migration failed (falling back to create_all): {_err}\n")

    def _try_start_backend() -> Optional[_sp.Popen]:
        """Attempt to start the generated backend. Returns process or None on immediate crash."""
        log_file = open(log_path, "a")
        log_file.write(f"[AetherOS] Starting generated backend on port {port} from {backend_dir}\n")
        log_file.flush()
        proc = _sp.Popen(
            [_sys.executable, "-m", "uvicorn", "src.main:app",
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(backend_dir),
            stdout=log_file,
            stderr=log_file,
            shell=False,
            env=_env,
            start_new_session=True,  # detach so process survives gateway restarts
        )
        if proc.poll() is not None:
            log_file.write("[AetherOS] Backend crashed — falling back to frontend-only server\n")
            log_file.flush()
            return None
        return proc

    def _start_frontend_server() -> _sp.Popen:
        """Serve the built frontend with a tiny FastAPI stub when backend fails."""
        _stub_dir = root_dir / "_preview_stub"
        _stub_dir.mkdir(exist_ok=True)
        _stub_main = _stub_dir / "main.py"
        _dist_path = str(frontend_dist).replace("\\", "/") if frontend_dist and frontend_dist.is_dir() else None
        # Only write the stub if it's missing or still contains the old empty-data template
        _stub_needs_write = (
            not _stub_main.exists()
            or '"data": []' in _stub_main.read_text()
            or "_MOCK_ROWS" not in _stub_main.read_text()
        )
        if not _stub_needs_write:
            # Custom stub already on disk — just launch it
            log_file = open(log_path, "a")
            log_file.write(f"[AetherOS] Reusing existing custom preview stub\n")
            log_file.flush()
            return _sp.Popen(
                [_sys.executable, "-m", "uvicorn", "main:app",
                 "--host", "127.0.0.1", "--port", str(port)],
                cwd=str(_stub_dir),
                stdout=log_file,
                stderr=log_file,
                shell=False,
                start_new_session=True,
            )
        _stub_main.write_text(
            f"""from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
import os, secrets, pathlib, re

app = FastAPI()

_PREVIEW_TOKEN = os.environ.get("PREVIEW_TOKEN", secrets.token_hex(32))
_MOCK_USER = {{"id": 1, "email": "admin@example.com", "name": "Admin User", "role": "admin"}}

_BANNER_SCRIPT = \"\"\"
<style>
  #__aether_crash_banner {{
    position: fixed; top: 0; left: 0; right: 0; z-index: 99999;
    background: #dc2626; color: #fff; font-family: monospace; font-size: 13px;
    padding: 8px 16px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,.4);
  }}
  #__aether_crash_banner a {{ color: #fef08a; text-decoration: underline; }}
</style>
<div id="__aether_crash_banner">
  ⚠ Backend failed to start — showing <strong>frontend skeleton only</strong>.
  All API calls return empty data. Check run logs for the root cause.
</div>
\"\"\"

@app.post("/api/auth/login")
@app.post("/api/v1/auth/login")
async def mock_login(request: Request):
    return JSONResponse({{"access_token": _PREVIEW_TOKEN, "token_type": "bearer", "user": _MOCK_USER}})

@app.get("/api/auth/me")
@app.get("/api/v1/auth/me")
async def mock_me():
    return JSONResponse(_MOCK_USER)

@app.post("/api/auth/logout")
async def mock_logout():
    return JSONResponse({{"success": True}})

@app.get("/api/{{path:path}}")
async def mock_api_get(path: str):
    return JSONResponse({{"items": [], "total": 0, "_preview_mode": True,
                          "_error": "Backend crashed — data unavailable"}})

@app.post("/api/{{path:path}}")
async def mock_api_post(path: str, request: Request):
    return JSONResponse({{"success": False, "_preview_mode": True,
                          "_error": "Backend crashed — write operations disabled"}}, status_code=503)

@app.put("/api/{{path:path}}")
async def mock_api_put(path: str, request: Request):
    return JSONResponse({{"success": False, "_preview_mode": True,
                          "_error": "Backend crashed — write operations disabled"}}, status_code=503)

@app.delete("/api/{{path:path}}")
async def mock_api_delete(path: str):
    return JSONResponse({{"success": False, "_preview_mode": True,
                          "_error": "Backend crashed — delete operations disabled"}}, status_code=503)

{"" if not _dist_path else f'''
_DIST = pathlib.Path(r"{_dist_path}")
if _DIST.is_dir():
    @app.get("/{{path:path}}", include_in_schema=False)
    def spa(path: str = ""):
        f = _DIST / path
        if f.is_file() and not f.name.endswith(".html"):
            return FileResponse(str(f))
        html_path = f if (f.is_file() and f.name.endswith(".html")) else _DIST / "index.html"
        html = html_path.read_text(encoding="utf-8")
        # Inject crash banner into <body>
        if "<body" in html and "_aether_crash_banner" not in html:
            html = html.replace("<body", _BANNER_SCRIPT + "<body", 1)
        return HTMLResponse(html)
'''}
"""
        )
        log_file = open(log_path, "a")
        log_file.write(f"[AetherOS] Starting frontend-only preview server on port {port}\n")
        log_file.flush()
        return _sp.Popen(
            [_sys.executable, "-m", "uvicorn", "main:app",
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(_stub_dir),
            stdout=log_file,
            stderr=log_file,
            shell=False,
            start_new_session=True,
        )

    try:
        proc = _try_start_backend()
        await asyncio.sleep(2)  # give the subprocess a moment to crash if it will
        mode = "backend"
        if proc is None:
            if frontend_dist and frontend_dist.is_dir():
                proc = _start_frontend_server()
                mode = "frontend_only"
            else:
                raise HTTPException(status_code=500, detail="Generated backend crashed and no frontend build available. Check the run log.")

        _run_procs[run_id] = proc
        _run_ports[run_id] = port
        _APP_DIRS[run_id] = str(root_dir)
        _APP_DIRS["__current__"] = str(root_dir)
        # Persist to Redis + in-memory state (cross-worker, survives restarts)
        try:
            from aether_os.core.app_state import set_app_state as _sas, set_proc as _sp_fn
            _sp_fn(run_id, proc)
            await _sas(run_id, port=port, pid=proc.pid, mode=mode, app_dir=str(root_dir))
        except Exception:
            pass
        # Persist state to disk so gateway restarts can recover without re-patching
        import json as _js_state, time as _ts_state
        _state_file = root_dir / "run_app_state.json"
        try:
            _state_file.write_text(_js_state.dumps({
                "run_id": run_id, "port": port, "pid": proc.pid,
                "started_at": _ts_state.time(), "mode": mode,
            }))
        except Exception:
            pass
        # Persist live_url so the "LAUNCH APP" button shows the correct proxied URL,
        # not a direct port that's blocked by the firewall.
        try:
            from aether_os.core.db_utils import async_update_run_live_url as _aulul
            await _aulul(run_id, "/app-preview/")
        except Exception:
            pass
        return {"status": "started", "port": port, "pid": proc.pid,
                "backend_dir": str(backend_dir),
                "mode": mode,
                "frontend_built": bool(frontend_dir and (frontend_dir / "dist").is_dir() and any((frontend_dir / "dist").iterdir())),
                "log": str(log_path),
                "preview_email": _preview_email,
                "preview_password": _PREVIEW_PASSWORD,
                "live_url": "/app-preview/",
                "preview_url": "/app-preview/"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start app: {e}")


@router.delete("/factory/runs/{run_id}/run-app")
async def stop_run_app(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Kill the background app process for a run."""
    _run_procs = _get_app_procs()
    _run_ports = _get_app_ports()
    proc = _run_procs.get(run_id)
    if proc is None or proc.poll() is not None:
        return {"status": "not_running"}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    del _run_procs[run_id]
    _run_ports.pop(run_id, None)
    try:
        from aether_os.core.app_state import clear_app_state as _cas, del_proc as _dp
        _dp(run_id)
        await _cas(run_id)
    except Exception:
        pass
    return {"status": "stopped", "run_id": run_id}


@router.get("/factory/runs/{run_id}/run-app/status")
async def run_app_status(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return whether the generated app is currently running."""
    import json as _json_s
    from aether_os.core.projects import get_project_manager as _gpm_s
    _run_procs = _get_app_procs()
    _run_ports = _get_app_ports()
    proc = _run_procs.get(run_id)
    running = proc is not None and proc.poll() is None
    port = _run_ports.get(run_id, int(os.environ.get("RUN_APP_PORT", "8001")))
    pid = proc.pid if running else None

    # Recovery: in-memory state is lost after gateway restarts. Read the persisted
    # run_app_state.json and confirm the PID is still alive before trusting it.
    if not running:
        try:
            root_dir = _gpm_s().get_project_dir(run_id).resolve()
            state_file = root_dir / "run_app_state.json"
            if state_file.exists():
                _s = _json_s.loads(state_file.read_text())
                _pid = _s.get("pid")
                _port = _s.get("port")
                if _pid and _port:
                    # Check if the process is still alive
                    import signal as _sig
                    try:
                        os.kill(_pid, 0)  # signal 0 = existence check, no kill
                        # PID is alive — restore in-memory state for this and future requests
                        running = True
                        port = _port
                        pid = _pid
                        _proc_obj = _ExternalProcess(_pid)
                        _run_procs[run_id] = _proc_obj
                        _run_ports[run_id] = _port
                        _APP_DIRS[run_id] = str(root_dir)
                        # Re-publish to Redis + in-memory state
                        try:
                            from aether_os.core.app_state import set_app_state as _sas2, set_proc as _sp2
                            _sp2(run_id, _proc_obj)
                            await _sas2(run_id, port=_port, pid=_pid,
                                        mode=_s.get("mode", "backend"), app_dir=str(root_dir))
                        except Exception:
                            pass
                        _APP_DIRS["__current__"] = str(root_dir)
                    except (ProcessLookupError, PermissionError):
                        pass  # PID is dead — ignore stale state
        except Exception:
            pass

    return {
        "running": running,
        "port": port,
        "pid": pid,
        "preview_url": "/app-preview/" if running else None,
    }


@router.get("/factory/runs/{run_id}/preview-credentials")
async def get_preview_credentials(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return demo login credentials for the generated app preview.

    Fix 23: Returns 503 with deployment_status if p11 has not completed.
    Fix 77: Returns 503 with container_crashed if credentials file missing.
    """
    import json as _json
    from aether_os.core.projects import get_project_manager
    from aether_os.core.db import get_session_factory as _gsf_pc
    from aether_os.core.models import PhaseCompletion as _PC_pc

    # Fix 23: check p11_deployment phase status
    try:
        async with _gsf_pc()() as _sess_pc:
            _p11 = await _sess_pc.get(_PC_pc, (run_id, "p11_deployment"))
            _p11_status = _p11.status if _p11 else "pending"
    except Exception:
        _p11_status = "unknown"

    if _p11_status not in ("passed", "completed"):
        raise HTTPException(
            status_code=503,
            detail={
                "detail": "app_not_deployed_yet",
                "deployment_status": _p11_status,
            },
        )

    root_dir = get_project_manager().get_project_dir(run_id).resolve()
    creds_path = root_dir / "preview_credentials.json"
    if creds_path.exists():
        return _json.loads(creds_path.read_text())

    # Fix 77: credentials file missing means app never started / crashed
    # Try seed.py as fallback before returning 503
    for seed_candidate in [
        root_dir / "p04_backend" / "backend_codegen" / "src" / "seed.py",
    ]:
        if seed_candidate.exists():
            import re as _re
            txt = seed_candidate.read_text()
            _email_m = _re.search(r'email\s*=\s*["\']([^"\']+@[^"\']+)["\']', txt)
            _pass_m  = _re.search(r'_ADMIN_PASSWORD\s*=\s*["\']([^"\']+)["\']', txt)
            if _email_m or _pass_m:
                return {
                    "email": _email_m.group(1) if _email_m else "admin@example.com",
                    "password": _pass_m.group(1) if _pass_m else "(check seed.py)",
                    "note": "Extracted from seed.py — run 'Run App' to get predictable credentials",
                }

    # Fix 77: no credentials file and no seed.py — app crashed or never started
    raise HTTPException(
        status_code=503,
        detail={
            "detail": "app_not_running",
            "reason": "container_crashed",
            "suggestion": "Check deployment logs for the error cause",
        },
    )


@router.get("/factory/runs/{run_id}/compliance")
async def get_run_compliance(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """
    Return the compliance scan result for a pipeline run.

    1. If a pre-generated compliance_scan.json exists (written by p06), return it.
    2. Otherwise run the real scanner on-demand against src/main.py.
    3. If neither is available, return a graceful 404-style response rather
       than raising so the UI can show a clear "not yet scanned" state.
    """
    from aether_os.core.compliance.code_scanner import scan_file
    from aether_os.core.compliance.pdf_report import generate_pdf
    from dataclasses import asdict

    project_dir = pathlib.Path.home() / ".aether_os" / "projects" / run_id

    # Fast path: p06 already wrote the JSON
    pre_built = project_dir / "p06_review_security" / "compliance" / "compliance_scan.json"
    if pre_built.exists():
        try:
            data = json.loads(pre_built.read_text(encoding="utf-8"))
            # Attach pdf_path if the PDF exists alongside the JSON
            pdf_sibling = pre_built.with_name("compliance_report.pdf")
            data["pdf_path"] = str(pdf_sibling) if pdf_sibling.exists() else None
            return data
        except Exception:
            pass  # fall through to on-demand scan

    # On-demand scan: find src/main.py
    main_py: Optional[pathlib.Path] = None
    for candidate in [
        project_dir / "src" / "main.py",
        project_dir / "p04_backend" / "backend_codegen" / "src" / "main.py",
    ]:
        if candidate.exists():
            main_py = candidate
            break

    if not main_py:
        return {
            "run_id": run_id,
            "status": "not_available",
            "message": "Code generation has not completed yet or src/main.py was not found.",
            "score": None,
            "findings": [],
        }

    # Pull project_name / domain from DB (best-effort)
    _project_name = ""
    _domain = "general"
    try:
        from aether_os.core.db import get_session_factory as _gsf_rc
        from aether_os.core.models import Run as _Run_rc
        from sqlalchemy import select as _sel_rc
        _sf_rc = _gsf_rc()
        async with _sf_rc() as _sess_rc:
            _run_rc = (await _sess_rc.execute(
                _sel_rc(_Run_rc).where(_Run_rc.id == run_id, _Run_rc.org_id == user["org_id"])
            )).scalar_one_or_none()
            if _run_rc:
                _project_name = getattr(_run_rc, "project_name", "") or ""
                _domain = getattr(_run_rc, "domain", "general") or "general"
    except Exception:
        pass

    scan_result = scan_file(main_py, project_name=_project_name, domain=_domain)

    # Persist the result so subsequent calls are fast
    try:
        scan_dir = project_dir / "p06_review_security" / "compliance"
        scan_dir.mkdir(parents=True, exist_ok=True)
        json_path = scan_dir / "compliance_scan.json"
        json_path.write_text(
            json.dumps(asdict(scan_result), indent=2, default=str),
            encoding="utf-8",
        )
        pdf_path = scan_dir / "compliance_report.pdf"
        generate_pdf(scan_result, pdf_path)
    except Exception:
        pdf_path = None

    result_dict = asdict(scan_result)
    result_dict["pdf_path"] = str(pdf_path) if pdf_path and pdf_path.exists() else None
    return result_dict


@router.get("/factory/runs/{run_id}/decisions")
async def get_run_decisions(
    run_id: str,
    status: Optional[str] = None,
    user: Dict[str, Any] = _current_user(),
):
    from aether_os.core.decisions.decision_engine import get_decision_engine
    engine = get_decision_engine()
    decisions = await engine.list_for_run(run_id, status=status)
    return [d.to_dict() for d in decisions]


@router.post("/factory/runs/{run_id}/decisions/{decision_id}/approve")
async def approve_decision(
    run_id: str,
    decision_id: str,
    user: Dict[str, Any] = _current_user(),
):
    from aether_os.core.decisions.decision_engine import get_decision_engine
    from aether_os.core.pipeline_state import publish_event as _pub_evt
    engine = get_decision_engine()
    try:
        decision = await engine.resolve(
            decision_id=decision_id,
            org_id=user["org_id"],
            approved=True,
        )
        # Fix 22: emit gate_approved into Redis so SSE replay knows decision was made
        try:
            await _pub_evt(run_id, {
                "type": "gate_approved",
                "decision_id": decision_id,
                "run_id": run_id,
                "ts": time.time(),
            })
        except Exception:
            pass
        return decision.to_dict()
    except LookupError:
        # Fix 42: if not in DB, try to recover from Redis event history
        try:
            from aether_os.core.pipeline_state import get_event_history as _geh
            _history = await _geh(run_id)
            _redis_decision = None
            for _evt in _history:
                if (
                    _evt.get("type") in ("spec_review_ready", "PhaseApprovalRequired", "approval_required")
                    and str(_evt.get("decision_id", "")) == decision_id
                ):
                    _redis_decision = _evt
                    break
            if _redis_decision:
                # Re-create and resolve
                _new_d = await engine.request_approval(type(
                    "_RecoveredDecision", (), {
                        "run_id": run_id,
                        "org_id": user["org_id"],
                        "decision_type": _redis_decision.get("decision_type", "phase_escalation"),
                        "title": _redis_decision.get("title", "Recovered gate"),
                        "what": _redis_decision.get("what", "Recovered from Redis history"),
                        "why": "Decision record was wiped; recovered from Redis event history",
                        "phase": _redis_decision.get("phase", ""),
                        "timeout_seconds": 300,
                        "id": decision_id,
                    }
                )())
                _resolved = await engine.resolve(
                    decision_id=decision_id,
                    org_id=user["org_id"],
                    approved=True,
                )
                try:
                    await _pub_evt(run_id, {
                        "type": "gate_approved",
                        "decision_id": decision_id,
                        "run_id": run_id,
                        "ts": time.time(),
                        "recovered": True,
                    })
                except Exception:
                    pass
                return _resolved.to_dict()
        except Exception:
            pass
        return {
            "detail": "gate_decision_wiped_by_recovery",
            "recovery_action": "pipeline_will_auto_proceed_in_600s",
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail="Decision belongs to a different org")


@router.post("/factory/runs/{run_id}/decisions/{decision_id}/decide")
async def decide_decision(
    run_id: str,
    decision_id: str,
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    from aether_os.core.decisions.decision_engine import get_decision_engine
    engine = get_decision_engine()
    approved = str(req.get("decision", "approve")).lower() == "approve"
    choice = req.get("choice")
    try:
        decision = await engine.resolve(
            decision_id=decision_id,
            org_id=user["org_id"],
            approved=approved,
            choice=choice,
        )
        return decision.to_dict()
    except LookupError:
        raise HTTPException(status_code=404, detail="Decision not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Decision belongs to a different org")


# ── Spec review gate ──────────────────────────────────────────────────────────

@router.get("/factory/runs/{run_id}/spec")
async def get_run_spec(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return the parsed requirements spec produced by p01_intake_requirements."""
    from pathlib import Path
    project_dir = Path(os.path.expanduser(f"~/.aether_os/projects/{run_id}"))
    # p01 writes requirements.json; fall back to legacy intake/intake.json
    _req_path = project_dir / "p01_intake_requirements" / "requirements.json"
    _intake_path = project_dir / "p01_intake_requirements" / "intake" / "intake.json"
    spec_path = _req_path if _req_path.exists() else _intake_path
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="Spec not ready — p01 has not completed yet")
    import json as _sj
    spec = _sj.loads(spec_path.read_text())
    # Also return run control state so the UI knows if spec review is pending
    from aether_os.core.pipeline_state import get_control as _gc
    control = await _gc(run_id)
    return {"spec": spec, "awaiting_approval": control == "spec_review"}


@router.post("/factory/runs/{run_id}/approve-spec")
async def approve_spec(
    run_id: str,
    body: Dict[str, Any] = {},
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Approve (or cancel) the parsed spec so the pipeline continues past the review gate."""
    from aether_os.core.pipeline_state import set_control as _sc, get_control as _gc
    ctrl = await _gc(run_id)
    if ctrl not in ("spec_review", "running", None):
        raise HTTPException(status_code=409, detail=f"Run is not at spec_review gate (current: {ctrl})")
    action = str(body.get("action", "approve")).lower()
    if action == "cancel":
        await _sc(run_id, "cancel")
        return {"status": "cancelled", "run_id": run_id}
    await _sc(run_id, "spec_approved")
    return {"status": "approved", "run_id": run_id}


# ── LLM Council multi-model code review ───────────────────────────────────────

@router.post("/factory/runs/{run_id}/council-review")
async def run_council_review(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """
    Run the generated src/main.py through the LLM Council for multi-model review.

    Dispatches up to 3 parallel model reviews (Claude, Gemini, Ollama).
    Any model whose API key is absent is silently skipped.
    Results are persisted to {project_dir}/council_review.json.

    Takes 30-60 seconds depending on model availability.
    """
    from pathlib import Path
    project_dir = Path(os.path.expanduser(f"~/.aether_os/projects/{run_id}"))
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    # Find src/main.py (same priority order as p11)
    main_py_candidates = [
        project_dir / "src" / "main.py",
        project_dir / "p04_backend" / "src" / "main.py",
        project_dir / "p04_backend" / "backend_codegen" / "src" / "main.py",
        project_dir / "p04a_backend_codegen" / "src" / "main.py",
    ]
    main_py = None
    for c in main_py_candidates:
        if c.exists():
            main_py = c
            break
    if main_py is None:
        # fallback: any main.py
        found = list(project_dir.rglob("main.py"))
        main_py = found[0] if found else None
    if main_py is None:
        raise HTTPException(
            status_code=404,
            detail="No main.py found for this run — run the pipeline first",
        )

    source_code = main_py.read_text(encoding="utf-8", errors="replace")

    # Resolve project_name and domain from DB (best-effort)
    _project_name = ""
    _domain = "general"
    try:
        from aether_os.core.db import get_session_factory as _gsf_cr
        from aether_os.core.models import Run as _Run_cr
        from sqlalchemy import select as _sel_cr
        async with _gsf_cr()() as _sess_cr:
            _run_cr = (await _sess_cr.execute(
                _sel_cr(_Run_cr).where(
                    _Run_cr.id == run_id,
                    _Run_cr.org_id == user["org_id"],
                )
            )).scalar_one_or_none()
            if _run_cr:
                _project_name = getattr(_run_cr, "project_name", "") or ""
                _domain = getattr(_run_cr, "domain", "general") or "general"
    except Exception:
        pass

    from aether_os.core.council.council_reviewer import run_council
    report = await run_council(
        source_code=source_code,
        run_id=run_id,
        project_name=_project_name,
        domain=_domain,
    )

    # Persist to disk
    review_path = project_dir / "council_review.json"
    review_path.write_text(
        json.dumps(report.to_dict(), indent=2),
        encoding="utf-8",
    )

    return report.to_dict()


@router.get("/factory/runs/{run_id}/council-review")
async def get_council_review(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """Get the previously generated council review for a run."""
    from pathlib import Path
    project_dir = Path(os.path.expanduser(f"~/.aether_os/projects/{run_id}"))
    review_path = project_dir / "council_review.json"
    if not review_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No council review found — POST to this endpoint first",
        )
    try:
        return json.loads(review_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read council review: {exc}")


@router.post("/factory/runs/{run_id}/kill")
async def kill_run(run_id: str, user: Dict[str, Any] = _current_user()):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    from aether_os.core.pipeline_state import set_control
    from aether_os.core.db_utils import update_run_status
    await set_control(run_id, "cancel")
    await update_run_status(run_id, "cancelled", org_id=user["org_id"])
    return {"success": True, "run_id": run_id}


# ── Deployment endpoints ───────────────────────────────────────────────────────

@router.post("/factory/runs/{run_id}/deploy")
async def deploy_run(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Manually trigger Docker deployment (non-blocking)."""
    from aether_os.core.audit.ledger import get_ledger
    from aether_os.core.db_utils import async_update_run_live_url
    import subprocess as _sp
    import asyncio as _aio

    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    # Fast-fail Docker check — run in thread so we don't block the event loop
    def _docker_check():
        try:
            return _sp.run(["docker", "info"], capture_output=True, timeout=10)
        except Exception:
            return None

    check = await _aio.to_thread(_docker_check)
    if check is None or check.returncode != 0:
        # Docker unavailable — fall through to in-process preview
        logger.warning("Docker unavailable for run %s — falling back to in-process preview", run_id)
        await start_run_app(run_id=run_id, user=user)
        return {
            "success": True,
            "live_url": "/app-preview/",
            "mode": "preview",
            "message": "Docker unavailable — using in-process preview",
        }

    from types import SimpleNamespace
    from aether_os.phases.p11_deployment.task_agent import TaskAgent

    # TaskAgent.run() may do blocking I/O — run in thread
    def _run_agent():
        import asyncio
        agent = TaskAgent()
        phase_input = SimpleNamespace(run_id=run_id)
        return asyncio.run(agent.run(phase_input))

    result = await _aio.to_thread(_run_agent)

    if result.get("success") and result.get("live_url"):
        try:
            await async_update_run_live_url(run_id, result["live_url"])
        except Exception as _e:
            logger.warning("Failed to persist live_url: %s", _e)

    return result


@router.delete("/factory/runs/{run_id}/deploy")
async def stop_deployment(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Stop the running Docker container (non-blocking)."""
    from aether_os.core.audit.ledger import get_ledger
    from aether_os.core.db_utils import async_update_run_live_url
    import subprocess as _sp
    import asyncio as _aio

    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    container_name = f"aetheros-app-{run_id[:8]}"

    # Check whether Docker is available
    def _docker_check_stop():
        try:
            return _sp.run(["docker", "info"], capture_output=True, timeout=10)
        except Exception:
            return None

    docker_check = await _aio.to_thread(_docker_check_stop)
    if docker_check is None or docker_check.returncode != 0:
        # Docker unavailable — stop the in-process preview instead
        logger.warning("Docker unavailable for stop of run %s — stopping in-process preview", run_id)
        await stop_run_app(run_id=run_id, user=user)
        try:
            await async_update_run_live_url(run_id, None)
        except Exception as _e:
            logger.warning("Failed to clear live_url: %s", _e)
        return {"stopped": True, "container": container_name, "mode": "preview"}

    def _stop():
        return _sp.run(["docker", "rm", "-f", container_name], capture_output=True)

    result = await _aio.to_thread(_stop)
    try:
        await async_update_run_live_url(run_id, None)
    except Exception as _e:
        logger.warning("Failed to clear live_url: %s", _e)
    return {"stopped": result.returncode == 0, "container": container_name}


@router.get("/factory/runs/{run_id}/artifacts")
async def get_run_artifacts(run_id: str, user: Dict[str, Any] = _current_user()):
    """List artifacts for a run.

    Fix 78: Returns relative paths only (strips backend_codegen/src/ prefix).
    Fix 81: Filters run_app.log from non-superadmin users.
    """
    import os as _os
    import re as _re_art
    from pathlib import Path
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select
    sf = get_session_factory()
    async with sf() as session:
        run = (await session.execute(select(Run).where(Run.id == run_id, Run.org_id == user["org_id"]))).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    project_dir = Path.home() / ".aether_os" / "projects" / run_id
    artifacts = []
    _ARTIFACT_SKIP = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                      "node_modules", ".git", ".venv", "venv", ".aetheros"}
    _ALLOW_HIDDEN = {".env.example", ".gitignore", ".dockerignore", ".eslintrc",
                     ".prettierrc", ".editorconfig", ".nvmrc"}
    _ALLOW_HIDDEN_DIRS = {".github", ".devcontainer"}
    _is_superadmin = user.get("role") == "superadmin"

    def _relative_artifact_path(rel_str: str) -> str:
        """Fix 78: strip internal directory prefixes, keep only src/filename.py style."""
        # Strip everything up to and including backend_codegen/src/ or phase/src/
        _stripped = _re_art.sub(r'^.*?backend_codegen/src/', 'src/', rel_str)
        if _stripped == rel_str:
            _stripped = _re_art.sub(r'^p\d+[^/]*/(?:backend_codegen/)?src/', 'src/', rel_str)
        return _stripped

    if project_dir.exists():
        for fpath in sorted(project_dir.rglob("*")):
            if not fpath.is_file():
                continue
            rel = fpath.relative_to(project_dir)
            rel_str = str(rel)
            parts = rel.parts
            if any(p in _ARTIFACT_SKIP for p in parts):
                continue
            # Fix 81: filter run_app.log for non-superadmin
            if fpath.name == "run_app.log" and not _is_superadmin:
                continue
            # Allow .github/ and .devcontainer/ dirs; allow known dotfiles; skip everything else hidden
            if any(p.startswith('.') for p in parts):
                if not (parts[0] in _ALLOW_HIDDEN_DIRS or fpath.name in _ALLOW_HIDDEN):
                    continue
            if fpath.suffix in {".pyc", ".pyo"}:
                continue
            # Fix 78: use relative path (strip absolute filesystem prefixes)
            _display_path = _relative_artifact_path(rel_str)
            artifacts.append({
                    "filename": fpath.name,
                    "path": _display_path,
                    "phase": rel.parts[0] if len(rel.parts) > 1 else "root",
                    "size_bytes": fpath.stat().st_size,
                    "created_at": int(fpath.stat().st_mtime * 1000),
                })
    return artifacts


@router.get("/factory/runs/{run_id}/download")
async def download_run_zip(run_id: str, user: Dict[str, Any] = _current_user()):
    import io, zipfile
    from pathlib import Path
    from fastapi.responses import StreamingResponse
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select
    sf = get_session_factory()
    async with sf() as session:
        run = (await session.execute(select(Run).where(Run.id == run_id, Run.org_id == user["org_id"]))).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    project_dir = Path.home() / ".aether_os" / "projects" / run_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project files not found")
    _SKIP = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
             "node_modules", ".git", ".venv", "venv", ".mypy_cache", ".aetheros"}
    _ALLOW_HIDDEN = {".env.example", ".gitignore", ".dockerignore", ".eslintrc",
                     ".prettierrc", ".editorconfig", ".nvmrc"}
    _ALLOW_HIDDEN_DIRS = {".github", ".devcontainer"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in sorted(project_dir.rglob("*")):
            if not fpath.is_file():
                continue
            rel = fpath.relative_to(project_dir)
            if rel.name == "run_preview.py":
                continue
            parts = rel.parts
            if any(p in _SKIP for p in parts):
                continue
            # Allow .github/ and .devcontainer/ dirs; allow known dotfiles; skip everything else hidden
            if any(p.startswith('.') for p in parts):
                if not (parts[0] in _ALLOW_HIDDEN_DIRS or fpath.name in _ALLOW_HIDDEN):
                    continue
            if fpath.suffix in {".pyc", ".pyo", ".db", ".db-shm", ".db-wal", ".log"}:
                continue
            try:
                if fpath.stat().st_size > 5 * 1024 * 1024:
                    continue
            except OSError:
                continue
            zf.write(fpath, rel)
    buf.seek(0)
    name = (run.project_name or run_id).replace(" ", "_")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={{"Content-Disposition": f'attachment; filename="{{name}}.zip"'}},
    )


@router.get("/factory/runs/{run_id}/portal")
async def get_run_portal(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Fix 75: Return portal HTML content path and run summary.

    Returns 404 with detail portal_not_generated if no portal data exists.
    """
    import pathlib as _pl
    from aether_os.core.db import get_session_factory as _gsf_portal
    from aether_os.core.models import Run as _Run_portal
    from sqlalchemy import select as _sel_portal

    async with _gsf_portal()() as _sess_portal:
        _run_p = (await _sess_portal.execute(
            _sel_portal(_Run_portal).where(
                _Run_portal.id == run_id,
                _Run_portal.org_id == user["org_id"],
            )
        )).scalar_one_or_none()
    if not _run_p:
        raise HTTPException(status_code=404, detail="Run not found")

    _project_dir = _pl.Path.home() / ".aether_os" / "projects" / run_id

    # Look for portal output from p14 or p10
    _portal_html: Optional[str] = None
    _portal_candidates = [
        _project_dir / "p14_client_portal" / "portal" / "index.html",
        _project_dir / "p14_client_portal" / "index.html",
        _project_dir / "p10_docs_delivery" / "portal" / "index.html",
        _project_dir / "p10_docs_delivery" / "index.html",
    ]
    for _cand in _portal_candidates:
        if _cand.exists():
            _portal_html = str(_cand.relative_to(_project_dir))
            break

    if not _portal_html:
        raise HTTPException(status_code=404, detail="portal_not_generated")

    # Gather deliverables list
    _deliverables = []
    for _phase in ("p10_docs_delivery", "p14_client_portal"):
        _phase_dir = _project_dir / _phase
        if _phase_dir.exists():
            for _f in sorted(_phase_dir.rglob("*")):
                if _f.is_file() and _f.suffix in (".html", ".pdf", ".zip", ".md", ".json"):
                    _deliverables.append({
                        "filename": _f.name,
                        "path": str(_f.relative_to(_project_dir)),
                        "size_bytes": _f.stat().st_size,
                    })

    _council = _run_p.council_delivery or {}
    return {
        "run_id": run_id,
        "portal_html_path": _portal_html,
        "summary": {
            "project_name": _run_p.project_name or f"project-{run_id[:8]}",
            "status": _run_p.status,
            "quality_score": _run_p.quality_score,
            "council_verdict": "passed" if _council.get("passed") else ("failed" if _council else "pending"),
        },
        "deliverables": _deliverables,
    }


@router.get("/factory/runs/{run_id}/traces")
async def get_run_traces(
    run_id: str,
    phase: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    user: Dict[str, Any] = _current_user(),
):
    """Return LLM call traces for a pipeline run (FIX 23)."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import LLMTrace
    from sqlalchemy import select
    
    sf = get_session_factory()
    async with sf() as db:
        q = select(LLMTrace).where(LLMTrace.run_id == run_id)
        if phase:
            q = q.where(LLMTrace.phase == phase)
        q = q.order_by(LLMTrace.created_at.asc()).limit(limit)
        result = await db.execute(q)
        traces = result.scalars().all()
        
        return [
            {
                "id": t.id,
                "phase": t.phase,
                "task_type": t.task_type,
                "model": t.model,
                "attempt": t.attempt,
                "duration_ms": t.duration_ms,
                "tokens_in": t.tokens_in,
                "tokens_out": t.tokens_out,
                "parsed_ok": t.parsed_ok,
                "error": t.error,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "has_prompt": bool(t.prompt),
                "has_response": bool(t.raw_response),
            }
            for t in traces
        ]


@router.get("/factory/runs/{run_id}/traces/{trace_id}")
async def get_trace_detail(
    run_id: str,
    trace_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """Return full prompt and response for a single trace (FIX 23)."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import LLMTrace
    from sqlalchemy import select
    
    sf = get_session_factory()
    async with sf() as db:
        result = await db.execute(
            select(LLMTrace).where(
                LLMTrace.id == trace_id,
                LLMTrace.run_id == run_id,
            )
        )
        trace = result.scalar_one_or_none()
        if not trace:
            raise HTTPException(status_code=404, detail="Trace not found")
        
        return {
            "id": trace.id,
            "phase": trace.phase,
            "task_type": trace.task_type,
            "model": trace.model,
            "prompt": trace.prompt,
            "raw_response": trace.raw_response,
            "parsed_ok": trace.parsed_ok,
            "error": trace.error,
            "attempt": trace.attempt,
            "duration_ms": trace.duration_ms,
            "tokens_in": trace.tokens_in,
            "tokens_out": trace.tokens_out,
            "created_at": trace.created_at.isoformat() if trace.created_at else None,
        }


@router.post("/factory/runs/{run_id}/push-github")
async def push_run_to_github(run_id: str, req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    """Push the generated project to a new GitHub repository."""
    import base64, httpx
    from pathlib import Path
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select
    github_token = req.get("github_token", "")
    repo_name = req.get("repo_name", "")
    if not github_token or not repo_name:
        raise HTTPException(status_code=422, detail="github_token and repo_name are required")
    sf = get_session_factory()
    async with sf() as session:
        run = (await session.execute(select(Run).where(Run.id == run_id, Run.org_id == user["org_id"]))).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    project_dir = Path.home() / ".aether_os" / "projects" / run_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project files not found")
    headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=30) as gh:
        # Create repo
        create_res = await gh.post("https://api.github.com/user/repos", json={
            "name": repo_name, "description": f"Generated by AetherOS Factory", "private": False, "auto_init": False,
        }, headers=headers)
        if create_res.status_code not in (201, 422):
            raise HTTPException(status_code=502, detail=f"GitHub repo creation failed: {create_res.text}")
        repo_data = create_res.json()
        html_url = repo_data.get("html_url", f"https://github.com/user/{repo_name}")
        # Get GitHub username
        user_res = await gh.get("https://api.github.com/user", headers=headers)
        gh_user = user_res.json().get("login", "aetheros")
        # Push files (up to 50 key files to avoid GitHub API limits)
        _SKIP = {"__pycache__", ".pytest_cache", "node_modules", ".git", ".venv", "venv"}
        _ALLOW_HIDDEN = {".env.example", ".gitignore", ".dockerignore", ".eslintrc",
                         ".prettierrc", ".editorconfig", ".nvmrc"}
        _ALLOW_HIDDEN_DIRS = {".github", ".devcontainer"}
        files_pushed = 0
        for fpath in sorted(project_dir.rglob("*")):
            if not fpath.is_file() or files_pushed >= 50:
                break
            rel = fpath.relative_to(project_dir)
            if rel.name == "run_preview.py":
                continue
            parts = rel.parts
            if any(p in _SKIP for p in parts):
                continue
            if any(p.startswith(".") for p in parts):
                if not (parts[0] in _ALLOW_HIDDEN_DIRS or fpath.name in _ALLOW_HIDDEN):
                    continue
            if fpath.suffix in {".pyc", ".pyo"}:
                continue
            try:
                content = base64.b64encode(fpath.read_bytes()).decode()
                await gh.put(
                    f"https://api.github.com/repos/{gh_user}/{repo_name}/contents/{rel}",
                    json={"message": f"Add {rel}", "content": content},
                    headers=headers,
                )
                files_pushed += 1
            except Exception:
                continue
    return {"html_url": html_url, "files_pushed": files_pushed}


# ── Builder specs (Frontend Builder / Backend Builder tabs) ───────────────────

@router.get("/factory/runs/{run_id}/frontend-spec")
async def get_frontend_spec(run_id: str, user: Dict[str, Any] = _current_user()):
    """Retrieve the frontend spec attached to a run."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import RunSpec, Run
    sf = get_session_factory()
    async with sf() as session:
        run = await session.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        row = await session.get(RunSpec, (run_id, "frontend"))
    return {"spec": row.spec if row else {}}


@router.post("/factory/runs/{run_id}/frontend-spec")
async def save_frontend_spec(
    run_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """Save / overwrite the frontend spec for a run."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import RunSpec, Run
    spec = body.get("spec") or body
    sf = get_session_factory()
    async with sf() as session:
        run = await session.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        row = await session.get(RunSpec, (run_id, "frontend"))
        if row:
            row.spec = spec
            row.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        else:
            session.add(RunSpec(run_id=run_id, spec_type="frontend", spec=spec))
        await session.commit()
    return {"status": "saved"}


@router.get("/factory/runs/{run_id}/backend-spec")
async def get_backend_spec(run_id: str, user: Dict[str, Any] = _current_user()):
    """Retrieve the backend spec attached to a run."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import RunSpec, Run
    sf = get_session_factory()
    async with sf() as session:
        run = await session.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        row = await session.get(RunSpec, (run_id, "backend"))
    return {"spec": row.spec if row else {}}


@router.post("/factory/runs/{run_id}/backend-spec")
async def save_backend_spec(
    run_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """Save / overwrite the backend spec for a run."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import RunSpec, Run
    spec = body.get("spec") or body
    sf = get_session_factory()
    async with sf() as session:
        run = await session.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        row = await session.get(RunSpec, (run_id, "backend"))
        if row:
            row.spec = spec
            row.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        else:
            session.add(RunSpec(run_id=run_id, spec_type="backend", spec=spec))
        await session.commit()
    return {"status": "saved"}


@router.post("/factory/runs/{run_id}/validate-spec")
async def validate_spec(
    run_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """Basic validation of a backend spec before pipeline starts."""
    spec = body.get("spec", {})
    errors = []
    if not spec.get("framework"):
        errors.append("framework is required")
    if not spec.get("database"):
        errors.append("database is required")
    entities = spec.get("entities", [])
    for i, ent in enumerate(entities):
        if not ent.get("name"):
            errors.append(f"entity[{i}] missing name")
        fields = ent.get("fields", [])
        if not any(f.get("primary_key") for f in fields):
            errors.append(f"entity '{ent.get('name', i)}' has no primary key field")
    return {"valid": len(errors) == 0, "errors": errors}


# ── Prompt Input Tab — conversation endpoint ──────────────────────────────────

@router.post("/factory/runs/{run_id}/chat")
async def project_chat(
    run_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """
    Project-scoped conversational AI endpoint.
    Messages are strictly scoped to the project — off-topic requests are redirected.
    """
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from aether_os.core.services import learning_service
    from aether_os.core.llm.client import LLMClient

    message = (body.get("message") or "").strip()
    history = body.get("history", [])  # list of {role, content}
    if not message:
        raise HTTPException(status_code=400, detail="message required")

    sf = get_session_factory()
    async with sf() as session:
        run = await session.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        user_ctx = await learning_service.get_user_context(
            org_id=user["org_id"], user_id=user["user_id"], session=session
        )
        project_name = run.project_name or run_id

    system_prompt = (
        "You are AetherOS, an autonomous software development assistant.\n\n"
        "SCOPE RESTRICTION — ABSOLUTE:\n"
        "You may ONLY discuss topics directly related to the current project:\n"
        "1. Software requirements and specifications\n"
        "2. Architecture, design patterns, and technical decisions\n"
        "3. Code review, debugging, and error analysis\n"
        "4. Testing strategy and coverage\n"
        "5. Deployment, infrastructure, and monitoring\n"
        "6. Performance optimization\n"
        "7. Security review of generated code\n"
        "8. Documentation and API specifications\n"
        "9. Change requests and iterations\n"
        "10. Project planning and timeline estimation\n\n"
        'You MUST refuse all other topics with: "I\'m focused on your project. '
        "Let's talk about [specific project topic]. What aspect of the project can I help you with?\"\n\n"
        f"Current project: {project_name}\n"
        f"User's learned preferences: {user_ctx}"
    )

    conversation = []
    for h in history[-10:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            conversation.append({"role": h["role"], "content": h["content"]})
    conversation.append({"role": "user", "content": message})

    try:
        client = LLMClient()
        reply = await client.call(
            prompt=message,
            task_type="code_generation",
            system=system_prompt,
            max_tokens=2048,
        )
    except Exception as e:
        logger.warning("Chat LLM call failed: %s", e)
        reply = "I'm having trouble connecting right now. Please try again shortly."

    return {"reply": reply, "run_id": run_id, "project": project_name}


# ── Council-review stuck-run cleanup ─────────────────────────────────────────

@router.post("/admin/runs/cleanup-council-review")
async def cleanup_stuck_council_review(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Promote runs stuck in 'council_review' for > 10 minutes to 'completed'.

    Intended for admin use or automated scheduling. Prevents indefinite stuck runs
    when the DeliveryCouncil background task silently fails.
    """
    if user.get("role") not in ("owner", "admin"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin or owner role required")

    import time as _time
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import Run as _Run
    from sqlalchemy import update as _upd, select as _sel

    cutoff = _time.time() - 600  # 10 minutes ago
    sf = _gsf()
    async with sf() as session:
        result = await session.execute(
            _upd(_Run)
            .where(_Run.status == "council_review")
            .where(_Run.started_at < cutoff)
            .values(status="completed")
        )
        await session.commit()
    promoted = result.rowcount
    logger.info("cleanup_stuck_council_review: promoted %d run(s) to completed", promoted)
    return {"promoted": promoted, "message": f"Promoted {promoted} stuck run(s) from council_review to completed"}
