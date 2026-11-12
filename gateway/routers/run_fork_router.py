"""AetherOS — re-run and branch: start a new build from a stage of an existing one.

Routes:
  POST /factory/runs/{run_id}/rerun   — new run of the same request, from a stage
  POST /factory/runs/{run_id}/branch  — new run (recorded as a branch), from a stage

Both start a new build, so both go through admit_run_start (policy plus the atomic
trial consume), and both resolve the stage id before anything is created: an
unknown id is a 422, not a run that fails the moment it starts.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.models import Run
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.policy_guard import admit_run_start
from aether_os.orchestrator.factory_pipeline import get_factory
from aether_os.orchestrator.phase_selector import canonical_stage_id
from aether_os.orchestrator.phase_sequence import PHASE_SEQUENCE

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])

# Strong references so in-flight builds are not garbage-collected.
_background_tasks: set = set()


class RerunRequest(BaseModel):
    from_phase: str


def _stage_or_422(stage_id: str) -> str:
    try:
        return canonical_stage_id(stage_id, PHASE_SEQUENCE)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _parent_or_404(run_id: str, org_id: str) -> Run:
    async with get_session_factory()() as session:
        parent = (await session.execute(
            select(Run).where(Run.id == run_id, Run.org_id == org_id))).scalar_one_or_none()
    if parent is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return parent


def _raw_input(parent: Run) -> str:
    return parent.raw_input or (parent.command or "").removeprefix("factory: ")


def _start(**kwargs: Any) -> None:
    async def _bg() -> None:
        try:
            await get_factory().run(**kwargs)
        except Exception as exc:
            logger.error("Run %s (from %s) failed: %s", kwargs["run_id"], kwargs["start_phase"], exc)

    task = asyncio.create_task(_bg())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.post("/factory/runs/{run_id}/rerun")
async def rerun_factory_run(
    run_id: str, req: RerunRequest, user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create a new run of the same request, starting at `from_phase`."""
    org_id = user.get("org_id")
    parent = await _parent_or_404(run_id, org_id)
    stage = _stage_or_422(req.from_phase)
    await admit_run_start(user, run_id)  # a rerun is a new run: same quota as /factory/start
    new_run_id = str(uuid.uuid4())
    _start(client_id=user.get("org_slug", "rerun"), raw_input=_raw_input(parent),
           start_phase=stage, run_id=new_run_id, org_id=org_id)
    return {"run_id": new_run_id, "status": "started", "from_phase": stage}


@router.post("/factory/runs/{run_id}/branch")
async def branch_factory_run(
    run_id: str, req: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Fork a run at a given stage — a new run with the same request (plus extra_input)."""
    org_id = user.get("org_id")
    parent = await _parent_or_404(run_id, org_id)
    stage = _stage_or_422(str(req.get("branch_phase") or "s03_backend"))
    await admit_run_start(user, run_id)  # a branch is a new run too
    raw_input = _raw_input(parent)
    extra_input = req.get("extra_input", "")
    if extra_input:
        raw_input = f"{raw_input}\n\nAdditional requirement: {extra_input}"
    new_run_id = str(uuid.uuid4())
    async with get_session_factory()() as session:
        session.add(Run(
            id=new_run_id, org_id=org_id, status="queued", parent_run_id=run_id, branch_phase=stage,
            raw_input=raw_input, domain=parent.domain or "general",
            project_name=f"{parent.project_name or 'project'} (branch)", started_at=time.time(),
        ))
        await session.commit()
    _start(client_id=user.get("org_slug", "branch"), raw_input=raw_input, start_phase=stage,
           run_id=new_run_id, org_id=org_id, domain=parent.domain or "general")
    return {"run_id": new_run_id, "status": "started", "parent_run_id": run_id, "branch_phase": stage}
