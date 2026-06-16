"""
AetherOS — Run Decisions Router
================================
Handles pipeline lifecycle control (pause/resume/cancel/kill/restart) and
compliance gate endpoints (approve, decide, validate-spec, spec, council-review,
cleanup-stuck).

Routes
------
  POST /factory/runs/{run_id}/pause
  POST /factory/runs/{run_id}/resume
  POST /factory/runs/{run_id}/cancel
  POST /factory/runs/{run_id}/kill
  POST /factory/runs/{run_id}/restart
  POST /factory/runs/{run_id}/decisions/{decision_id}/approve
  POST /factory/runs/{run_id}/decisions/{decision_id}/decide
  POST /factory/runs/{run_id}/validate-spec
  GET  /factory/runs/{run_id}/spec
  POST /factory/runs/{run_id}/approve-spec
  POST /factory/runs/{run_id}/council-review
  GET  /factory/runs/{run_id}/council-review
  POST /admin/runs/cleanup-council-review

Independently importable — no imports from factory_runs_router.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])


# ── Auth helper ────────────────────────────────────────────────────────────────

def _current_user():
    return Depends(get_current_user)


# ── Background-task registry ───────────────────────────────────────────────────

def _get_background_tasks() -> set:
    from aether_os.gateway import api as _api
    return _api._background_tasks


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/factory/runs/{run_id}/pause")
async def pause_factory_run(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Signal the pipeline to pause."""
    from aether_os.core.audit.ledger import get_ledger
    from aether_os.core.pipeline_state import set_control as _set_control
    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
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
    from aether_os.core.pipeline_state import set_control as _set_control
    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    await _set_control(run_id, "run")
    await get_ledger().async_update_run_status(run_id, "running")
    return {"run_id": run_id, "status": "running"}


@router.post("/factory/runs/{run_id}/cancel")
async def cancel_factory_run(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Cancel a running or paused pipeline run."""
    from aether_os.core.audit.ledger import get_ledger
    from aether_os.core.pipeline_state import set_control as _set_control
    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    await _set_control(run_id, "cancel")
    await get_ledger().async_update_run_status(run_id, "cancelled")
    return {"run_id": run_id, "status": "cancelled"}


@router.post("/factory/runs/{run_id}/kill")
async def kill_run(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Force-cancel a run (owner/admin only)."""
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403)
    from aether_os.core.pipeline_state import set_control
    from aether_os.core.db_utils import update_run_status
    await set_control(run_id, "cancel")
    await update_run_status(run_id, "cancelled", org_id=user["org_id"])
    return {"success": True, "run_id": run_id}


@router.post("/factory/runs/{run_id}/restart")
async def restart_factory_run(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Restart a crashed/failed run from its last saved checkpoint."""
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
    if _run_r.status not in ("failed", "cancelled", "error"):
        raise HTTPException(
            status_code=409,
            detail=f"Run is {_run_r.status}; only failed/cancelled runs can be restarted",
        )
    _ckpt = _run_r.checkpoint_data
    if not _ckpt or not isinstance(_ckpt, dict) or not _ckpt.get("last_completed_phase"):
        raise HTTPException(
            status_code=409,
            detail="No checkpoint saved for this run — use /rerun to start fresh",
        )

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


@router.post("/factory/runs/{run_id}/decisions/{decision_id}/approve")
async def approve_decision(
    run_id: str,
    decision_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """Approve a pending decision gate."""
    from aether_os.core.decisions.decision_engine import get_decision_engine
    from aether_os.core.pipeline_state import publish_event as _pub_evt
    engine = get_decision_engine()
    try:
        decision = await engine.resolve(
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
            })
        except Exception:
            pass
        return decision.to_dict()
    except LookupError:
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
    """Resolve a decision gate with approve/reject."""
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


@router.get("/factory/runs/{run_id}/spec")
async def get_run_spec(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return the parsed requirements spec produced by p01_intake_requirements."""
    import pathlib
    project_dir = pathlib.Path(os.path.expanduser(f"~/.aether_os/projects/{run_id}"))
    _req_path = project_dir / "p01_intake_requirements" / "requirements.json"
    _intake_path = project_dir / "p01_intake_requirements" / "intake" / "intake.json"
    spec_path = _req_path if _req_path.exists() else _intake_path
    if not spec_path.exists():
        raise HTTPException(
            status_code=404, detail="Spec not ready — p01 has not completed yet"
        )
    import json as _sj
    spec = _sj.loads(spec_path.read_text())
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
        raise HTTPException(
            status_code=409,
            detail=f"Run is not at spec_review gate (current: {ctrl})",
        )
    action = str(body.get("action", "approve")).lower()
    if action == "cancel":
        await _sc(run_id, "cancel")
        return {"status": "cancelled", "run_id": run_id}
    await _sc(run_id, "spec_approved")
    return {"status": "approved", "run_id": run_id}


@router.post("/factory/runs/{run_id}/council-review")
async def run_council_review(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """Run the generated src/main.py through the LLM Council for multi-model review."""
    import pathlib
    project_dir = pathlib.Path(os.path.expanduser(f"~/.aether_os/projects/{run_id}"))
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Run not found")

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
        found = list(project_dir.rglob("main.py"))
        main_py = found[0] if found else None
    if main_py is None:
        raise HTTPException(
            status_code=404,
            detail="No main.py found for this run — run the pipeline first",
        )

    source_code = main_py.read_text(encoding="utf-8", errors="replace")

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

    review_path = project_dir / "council_review.json"
    review_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    return report.to_dict()


@router.get("/factory/runs/{run_id}/council-review")
async def get_council_review(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """Get the previously generated council review for a run."""
    import pathlib
    project_dir = pathlib.Path(os.path.expanduser(f"~/.aether_os/projects/{run_id}"))
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


@router.post("/admin/runs/cleanup-council-review")
async def cleanup_stuck_council_review(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Promote runs stuck in 'council_review' for > 10 minutes to 'completed'.

    Intended for admin use or automated scheduling.
    """
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin or owner role required")

    import time as _time
    from aether_os.core.db import get_session_factory as _gsf
    from aether_os.core.models import Run as _Run
    from sqlalchemy import update as _upd

    cutoff = _time.time() - 600
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
    logger.info(
        "cleanup_stuck_council_review: promoted %d run(s) to completed", promoted
    )
    return {
        "promoted": promoted,
        "message": f"Promoted {promoted} stuck run(s) from council_review to completed",
    }
