"""AetherOS — answers to the domain model's clarifying questions.

  GET  /factory/runs/{run_id}/clarifying-answers   questions and the answers recorded so far
  POST /factory/runs/{run_id}/clarifying-answers   {answers: {field_path: value}, restart: false}

Answers are checked against the questions s02 stored for THIS run (unknown field, value outside
the question's options, empty or oversized value: 422), recorded in a gateway-owned file and in
the ledger (field names and a digest, not the text), and read by s02 on its next run
(orchestrator/clarifying.py). With restart=true the run is re-run from s02, keeping stage 1's
context, so the domain model is rebuilt with the answers.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from aether_os.core.audit.ledger import get_ledger
from aether_os.core.db import get_session_factory
from aether_os.core.models import Run
from aether_os.gateway.dependencies import require_run_user
from aether_os.gateway.policy_guard import enforce
from aether_os.gateway.services.run_start import BUSY_STATUSES, claim_run, start_in_background
from aether_os.orchestrator import clarifying

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])

RESTART_FROM = "s02_architecture"
_BUSY = BUSY_STATUSES


class AnswersRequest(BaseModel):
    answers: Dict[str, Any] = Field(max_length=clarifying.MAX_ANSWERS)
    restart: bool = False


async def _run_or_404(run_id: str, org_id: str) -> Run:
    async with get_session_factory()() as session:
        run = await session.get(Run, run_id)
    if run is None or run.org_id != org_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


@router.get("/factory/runs/{run_id}/clarifying-answers")
async def get_clarifying_answers(
    run_id: str, user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, Any]:
    return {"run_id": run_id, "questions": clarifying.stored_questions(run_id),
            "answers": clarifying.load_answers(run_id)}


@router.post("/factory/runs/{run_id}/clarifying-answers")
async def submit_clarifying_answers(
    run_id: str, req: AnswersRequest, user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, Any]:
    await enforce("run.clarify", user, run_id)
    run = await _run_or_404(run_id, user["org_id"])
    questions = clarifying.stored_questions(run_id)
    if not questions:
        raise HTTPException(status_code=409, detail="This run has no open clarifying questions")
    try:
        clean = clarifying.validate(questions, req.answers)
    except clarifying.AnswersRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ckpt = run.checkpoint_data if isinstance(run.checkpoint_data, dict) else None
    if req.restart:
        # Checked before anything is recorded: a refused restart must not half-apply.
        await enforce("run.restart", user, run_id)
        if run.status in _BUSY:
            raise HTTPException(status_code=409, detail=f"Run is {run.status}; wait for it to stop first")
        if not ckpt or not ckpt.get("accumulated_context"):
            raise HTTPException(status_code=409, detail="No checkpoint saved for this run: use /rerun")

    merged = clarifying.save_answers(run_id, clean)
    await get_ledger().async_log_audit_event(
        org_id=user["org_id"], user_id=user.get("user_id") or user.get("sub") or "-",
        action="run.clarifying_answers", resource_type="run", resource_id=run_id,
        metadata={"fields": sorted(clean), "digest": clarifying.digest(clean), "restart": req.restart})

    if req.restart:
        # Resume AT s02: stage 1's saved context is kept, s02 onwards runs again. One
        # conditional UPDATE: of two concurrent restarts only one matches and starts a build.
        if not await claim_run(run_id, user["org_id"], not_in=_BUSY, values=dict(
                status="running", message=None,
                checkpoint_data={**ckpt, "last_completed_phase": "s01_intake"})):
            raise HTTPException(status_code=409, detail="Run is already running; wait for it to stop first")
        start_in_background(client_id=user.get("org_slug", "clarify"),
                            raw_input=(run.raw_input or run.command or "").removeprefix("factory: "),
                            run_id=run_id, org_id=user["org_id"])
    return {"run_id": run_id, "recorded": sorted(clean), "answers": merged,
            "restarted": req.restart, "restart_from": RESTART_FROM if req.restart else None}
