"""
AetherOS — Run Decisions Router
================================
Handles pipeline lifecycle control (pause/resume/cancel/kill/restart).

Routes
------
  POST /factory/runs/{run_id}/pause
  POST /factory/runs/{run_id}/resume
  POST /factory/runs/{run_id}/cancel
  POST /factory/runs/{run_id}/kill
  POST /factory/runs/{run_id}/restart

Spec validation, approval, council-review, and decision-gate routes live in
run_spec_router.py.

Independently importable — no imports from factory_runs_router.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from aether_os.gateway.dependencies import get_current_user, require_run_user
from aether_os.gateway.policy_guard import enforce
from aether_os.gateway.services.run_start import RESTARTABLE_STATUSES, claim_run

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
    user: Dict[str, Any] = Depends(require_run_user),
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
    from sqlalchemy import select as _sel_restart
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
    if _run_r.status not in RESTARTABLE_STATUSES:
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
    await enforce("run.restart", user, run_id)

    if not await claim_run(run_id, org_id, only_in=RESTARTABLE_STATUSES, values={"status": "running"}):
        raise HTTPException(status_code=409, detail="Run is no longer restartable (another restart won)")

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

# Spec validation, decision gates, council-review, and cleanup routes live in
# run_spec_router.py — see gateway/routers/run_spec_router.py
