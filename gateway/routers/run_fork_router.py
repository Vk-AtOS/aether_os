"""AetherOS — re-run and branch: start a new build from a stage of an existing one.

Routes:
  POST /factory/runs/{run_id}/rerun   — new run of the same request, from a stage
  POST /factory/runs/{run_id}/branch  — new run (recorded as a branch), from a stage

Both start a new build, so both go through admit_run_start (policy plus the atomic
trial consume), and both resolve the stage id before anything is created: an
unknown id is a 422, not a run that fails the moment it starts.

The new run starts with a COPY of the parent's project folder, edited files included
(core/project_copy.py: secrets, .env, venvs, node_modules and run-app state are left out; size
limited, a folder over the limit is a 413 before anything is created). `source_run_id` (same
organisation) takes the files from another run; `copy_files: false` starts from an empty folder.
parent_run_id and branch_phase are recorded on the new run for both routes.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core import project_copy
from aether_os.core.audit.ledger import get_ledger
from aether_os.core.models import Run
from aether_os.core.projects import get_project_manager
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.policy_guard import admit_run_start
from aether_os.gateway.services.run_start import start_in_background
from aether_os.orchestrator.phase_selector import canonical_stage_id
from aether_os.orchestrator.phase_sequence import PHASE_SEQUENCE

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])

class RerunRequest(BaseModel):
    from_phase: str
    source_run_id: Optional[str] = None   # take the files from this run (same org); default: the parent
    copy_files: bool = True


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


async def _plan_copy(source_id: Optional[str], parent_id: str, org_id: str,
                     copy_files: bool) -> Tuple[Optional[str], list]:
    """(source run id, plan) — checked BEFORE the run is admitted, so a refusal costs nothing."""
    if not copy_files:
        return None, []
    source = source_id or parent_id
    if source != parent_id:
        await _parent_or_404(source, org_id)   # another run's files only if it is this org's
    try:
        plan = await asyncio.to_thread(project_copy.plan_copy, get_project_manager().get_project_dir(source))
    except project_copy.ProjectTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return source, plan


async def _copy_and_record(user: Dict[str, Any], new_run_id: str, parent_id: str,
                           source: Optional[str], plan: List[Tuple[str, int]], action: str) -> int:
    copied = 0
    if source is not None:
        pm = get_project_manager()
        copied = await asyncio.to_thread(project_copy.copy_project, pm.get_project_dir(source),
                                         pm.get_project_dir(new_run_id), plan)
    await get_ledger().async_log_audit_event(
        org_id=user["org_id"], user_id=user.get("user_id") or user.get("sub") or "-", action=action,
        resource_type="run", resource_id=new_run_id,
        metadata={"parent_run_id": parent_id, "source_run_id": source, "files_copied": copied})
    return copied


async def _create_run(new_run_id: str, org_id: str, parent: Run, parent_id: str, stage: str,
                      raw_input: str, label: str) -> None:
    async with get_session_factory()() as session:
        session.add(Run(
            id=new_run_id, org_id=org_id, status="queued", parent_run_id=parent_id, branch_phase=stage,
            raw_input=raw_input, domain=parent.domain or "general",
            project_name=f"{parent.project_name or 'project'}{label}", started_at=time.time(),
        ))
        await session.commit()


@router.post("/factory/runs/{run_id}/rerun")
async def rerun_factory_run(
    run_id: str, req: RerunRequest, user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create a new run of the same request, starting at `from_phase`, on a copy of the parent's files."""
    org_id = user.get("org_id")
    parent = await _parent_or_404(run_id, org_id)
    stage = _stage_or_422(req.from_phase)
    source, plan = await _plan_copy(req.source_run_id, run_id, org_id, req.copy_files)
    await admit_run_start(user, run_id)  # a rerun is a new run: same quota as /factory/start
    new_run_id = str(uuid.uuid4())
    copied = await _copy_and_record(user, new_run_id, run_id, source, plan, "run.rerun")
    await _create_run(new_run_id, org_id, parent, run_id, stage, _raw_input(parent), "")
    start_in_background(client_id=user.get("org_slug", "rerun"), raw_input=_raw_input(parent),
                        start_phase=stage, run_id=new_run_id, org_id=org_id,
                        domain=parent.domain or "general")
    return {"run_id": new_run_id, "status": "started", "from_phase": stage, "parent_run_id": run_id,
            "branch_phase": stage, "source_run_id": source, "files_copied": copied}


@router.post("/factory/runs/{run_id}/branch")
async def branch_factory_run(
    run_id: str, req: Dict[str, Any], user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Fork a run at a given stage: a new run with the same request (plus extra_input), on a copy of its files."""
    org_id = user.get("org_id")
    parent = await _parent_or_404(run_id, org_id)
    stage = _stage_or_422(str(req.get("branch_phase") or "s03_backend"))
    source, plan = await _plan_copy(req.get("source_run_id"), run_id, org_id, req.get("copy_files", True) is not False)
    await admit_run_start(user, run_id)  # a branch is a new run too
    raw_input = _raw_input(parent)
    extra_input = req.get("extra_input", "")
    if extra_input:
        raw_input = f"{raw_input}\n\nAdditional requirement: {extra_input}"
    new_run_id = str(uuid.uuid4())
    copied = await _copy_and_record(user, new_run_id, run_id, source, plan, "run.branch")
    await _create_run(new_run_id, org_id, parent, run_id, stage, raw_input, " (branch)")
    start_in_background(client_id=user.get("org_slug", "branch"), raw_input=raw_input, start_phase=stage,
                        run_id=new_run_id, org_id=org_id, domain=parent.domain or "general")
    return {"run_id": new_run_id, "status": "started", "parent_run_id": run_id, "branch_phase": stage,
            "source_run_id": source, "files_copied": copied}
