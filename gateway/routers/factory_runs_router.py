"""
AetherOS — Factory Runs Router
Extracted from gateway/api.py

Routes (core run lifecycle, file management, streaming, compliance):
  GET  /factory/runs/{run_id}/test-report
  GET  /factory/runs
  GET  /factory/runs/{run_id}
  GET  /factory/runs/{run_id}/quality
  GET  /factory/runs/{run_id}/snapshots
  GET  /factory/runs/{run_id}/snapshots/{snapshot_id}
  POST /factory/runs/{run_id}/memory/changelog
  POST /factory/runs/{run_id}/priority
  POST /factory/runs/{run_id}/rerun
  POST /factory/runs/{run_id}/branch
  POST /factory/runs/{run_id}/sse-token
  GET  /factory/runs/{run_id}/stream
  GET  /factory/runs/{run_id}/files
  GET  /factory/runs/{run_id}/file-content
  PATCH /factory/runs/{run_id}/file-content
  POST /factory/runs/{run_id}/open-in-vscode
  GET  /factory/runs/{run_id}/envvars
  PATCH /factory/runs/{run_id}/envvars
  GET  /factory/runs/{run_id}/compliance
  GET  /factory/runs/{run_id}/decisions
  GET  /factory/runs/{run_id}/portal

Moved to focused routers:
  run_app_router       — POST/DELETE/GET run-app, preview-credentials, preview
  run_decisions_router — pause/resume/cancel/kill/restart, decisions/approve/decide,
                         spec, approve-spec, validate-spec, council-review, cleanup
  run_deploy_router    — deploy, artifacts, download, push-github, traces,
                         frontend-spec, backend-spec, chat
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
