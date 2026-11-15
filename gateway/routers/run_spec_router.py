"""
AetherOS — Run Spec Router
==========================
Handles spec validation, spec retrieval, approval, council review, and the
admin cleanup endpoint.  Lifecycle control (pause/resume/cancel/kill/restart)
and decision gates live in run_decisions_router.py.

Routes
------
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

import json
import logging
import os
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from aether_os.core.run_app import safe_fs
from aether_os.core.spec_approval import decide_spec
from aether_os.core.decisions.decision_engine import AlreadyDecided
from aether_os.gateway.dependencies import get_current_user, require_run_user
from aether_os.gateway.policy_guard import enforce

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])


# ── Auth helper ────────────────────────────────────────────────────────────────

def _current_user():
    return Depends(get_current_user)


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/factory/runs/{run_id}/decisions/{decision_id}/approve")
async def approve_decision(
    run_id: str,
    decision_id: str,
    user: Dict[str, Any] = Depends(require_run_user),
):
    """Approve a pending decision gate (member or above; a viewer reads, never decides).

    DEPRECATED: duplicate of POST .../decide with {"decision": "approve"}, which the dashboard uses.
    """
    await enforce("decision.decide", user)
    from aether_os.core.decisions.decision_engine import get_decision_engine
    from aether_os.core.pipeline_state import publish_event as _pub_evt
    engine = get_decision_engine()
    try:
        decision = await engine.resolve(
            decision_id=decision_id,
            org_id=user["org_id"],
            approved=True,
            run_id=run_id,
        )
        try:
            await _pub_evt(run_id, {
                "type": "gate_approved",
                "decision_id": decision_id,
                "run_id": run_id,
                "ts": time.time(),
            })
        except Exception as exc:
            logger.debug("publish_event gate_approved skipped: %s", exc)
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
                except Exception as exc:
                    logger.debug("publish_event recovered gate_approved skipped: %s", exc)
                return _resolved.to_dict()
        except Exception as exc:
            logger.debug("approve_decision recovery attempt failed: %s", exc)
        return {
            "detail": "gate_decision_wiped_by_recovery",
            "recovery_action": "pipeline_will_auto_proceed_in_600s",
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail="Decision belongs to a different org") from None
    except AlreadyDecided as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/factory/runs/{run_id}/decisions/{decision_id}/decide")
async def decide_decision(
    run_id: str,
    decision_id: str,
    req: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_run_user),
):
    """Resolve a decision gate with approve/reject (member or above)."""
    await enforce("decision.decide", user)
    from aether_os.core.decisions.decision_engine import get_decision_engine
    engine = get_decision_engine()
    # Fail closed: a body that says neither way is refused. (It used to default to approve, and the dashboard
    # sent {approved: false}, which the server did not read, so every Reject approved the gate.)
    if isinstance(req.get("approved"), bool):
        approved = req["approved"]
    elif str(req.get("decision", "")).lower() in ("approve", "deny", "reject"):
        approved = str(req["decision"]).lower() == "approve"
    else:
        raise HTTPException(status_code=422, detail="decision must be 'approve' or 'deny' (or approved: true/false)")
    choice = req.get("choice")
    try:
        decision = await engine.resolve(
            decision_id=decision_id,
            org_id=user["org_id"],
            approved=approved,
            choice=choice,
            run_id=run_id,
        )
        return decision.to_dict()
    except LookupError:
        raise HTTPException(status_code=404, detail="Decision not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Decision belongs to a different org") from None
    except AlreadyDecided as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/factory/runs/{run_id}/validate-spec")
async def validate_spec(
    run_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_run_user),
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
    user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, Any]:
    """Return the parsed requirements spec produced by p01_intake_requirements."""
    import pathlib
    project_dir = pathlib.Path(os.path.expanduser(f"~/.aether_os/projects/{run_id}"))
    # safe_fs: the sandboxed app writes in project_dir; a planted link reads as "not there".
    spec_text = safe_fs.read_text_or_none(project_dir, "p01_intake_requirements/requirements.json")
    if spec_text is None:
        spec_text = safe_fs.read_text_or_none(project_dir, "p01_intake_requirements/intake/intake.json")
    if spec_text is None:
        raise HTTPException(
            status_code=404, detail="Spec not ready — p01 has not completed yet"
        )
    import json as _sj
    spec = _sj.loads(spec_text)
    from aether_os.core.pipeline_state import get_control as _gc
    control = await _gc(run_id)
    return {"spec": spec, "awaiting_approval": control == "spec_review"}


@router.post("/factory/runs/{run_id}/approve-spec")
async def approve_spec(
    run_id: str,
    body: Dict[str, Any] = {},
    user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, Any]:
    """Approve (or cancel) the parsed spec so the pipeline continues past the review gate.

    Goes through core.spec_approval.decide_spec, the same ledgered path the client
    portal and Prime use: 409 unless the run is waiting at the gate.
    """
    action = str(body.get("action", "approve")).lower()
    outcome = await decide_spec(
        run_id, user["org_id"], actor=str(user.get("user_id") or user.get("sub") or "-"),
        via="dashboard", approve=action != "cancel")
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="Run not found")
    if outcome.startswith("not_waiting:"):
        raise HTTPException(
            status_code=409,
            detail=f"Run is not at spec_review gate (current: {outcome.split(':', 1)[1]})",
        )
    return {"status": outcome, "run_id": run_id}


@router.post("/factory/runs/{run_id}/council-review")
async def run_council_review(
    run_id: str,
    user: Dict[str, Any] = Depends(require_run_user),
):
    """Run the generated src/main.py through the LLM Council for multi-model review."""
    import pathlib
    project_dir = pathlib.Path(os.path.expanduser(f"~/.aether_os/projects/{run_id}"))
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    main_py_candidates = [
        "src/main.py",
        "p04_backend/src/main.py",
        "p04_backend/backend_codegen/src/main.py",
        "p04a_backend_codegen/src/main.py",
    ]
    source_code = None
    for c in main_py_candidates:
        source_code = safe_fs.read_text_or_none(project_dir, c)
        if source_code is not None:
            break
    if source_code is None:   # links are never entered or followed
        for rel in safe_fs.walk_files(project_dir):
            if rel.name == "main.py":
                source_code = safe_fs.read_text_or_none(project_dir, rel)
                if source_code is not None:
                    break
    if source_code is None:
        raise HTTPException(
            status_code=404,
            detail="No main.py found for this run — run the pipeline first",
        )

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
    except Exception as exc:
        logger.debug("council_review: failed to fetch run metadata: %s", exc)

    from aether_os.core.council.council_reviewer import run_council
    report = await run_council(
        source_code=source_code,
        run_id=run_id,
        project_name=_project_name,
        domain=_domain,
        org_id=user["org_id"],
    )

    safe_fs.safe_write_text(project_dir, project_dir / "council_review.json",
                            json.dumps(report.to_dict(), indent=2))

    return report.to_dict()


@router.get("/factory/runs/{run_id}/council-review")
async def get_council_review(
    run_id: str,
    user: Dict[str, Any] = Depends(require_run_user),
):
    """Get the previously generated council review for a run."""
    import pathlib
    project_dir = pathlib.Path(os.path.expanduser(f"~/.aether_os/projects/{run_id}"))
    review_text = safe_fs.read_text_or_none(project_dir, "council_review.json")
    if review_text is None:
        raise HTTPException(
            status_code=404,
            detail="No council review found — POST to this endpoint first",
        )
    try:
        return json.loads(review_text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read council review: {exc}") from exc


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
            .where(_Run.org_id == user["org_id"])  # an org admin touches their own org's runs only
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
