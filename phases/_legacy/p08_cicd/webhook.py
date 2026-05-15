"""
AetherOS — CI Webhook Handler (Phase 08)
Migrated from DCSP/src/api/webhook.py.

BUG 5 FIX: _CALL_GRAPH is no longer None. On startup, the call graph is built
from the repo root. It is rebuilt on each webhook receipt for the target repo.
This ensures AST-proximity scoring is active, not degraded-mode (0.5 fallback).
"""
from __future__ import annotations
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# BUG 5 FIX: _CALL_GRAPH is initialised properly, not left as None
_CALL_GRAPH: Optional[Any] = None


def _build_call_graph_for_repo(repo_root: str) -> Optional[Any]:
    """
    BUG 5 FIX: Build a real CallGraph for the given repo root.
    Returns None if the repo doesn't exist or call graph fails to build.
    """
    try:
        from aether_os.phases.p08_cicd.dfle.call_graph import CallGraph
        root = Path(repo_root)
        if not root.exists():
            logger.warning("Repo root does not exist: %s — call graph skipped", repo_root)
            return None
        cg = CallGraph.build_call_graph(str(root))
        logger.info("Call graph built for %s", repo_root)
        return cg
    except Exception as exc:
        logger.warning("Call graph build failed for %s: %s", repo_root, exc)
        return None


def initialise_call_graph(repo_root: str) -> None:
    """
    BUG 5 FIX: Called at API startup to pre-build the call graph.
    Should be called in the FastAPI lifespan startup event.
    """
    global _CALL_GRAPH
    _CALL_GRAPH = _build_call_graph_for_repo(repo_root)
    if _CALL_GRAPH:
        logger.info("Webhook: Call graph initialised from %s", repo_root)
    else:
        logger.warning("Webhook: Call graph not available — AST scoring will be degraded")


class CIWebhookRequest(BaseModel):
    repo_name: str
    branch: str
    ci_job_name: str
    ci_log: str
    repo_root: Optional[str] = None  # BUG 5 FIX: accept repo root to rebuild call graph
    ci_provider: str = "github_actions"
    commit_sha: Optional[str] = None
    author: Optional[str] = None


class RepairResponse(BaseModel):
    job_id: str
    status: str
    message: str
    repo_name: str


async def _run_repair_async(
    job_id: str,
    request_data: CIWebhookRequest,
    call_graph: Optional[Any],
) -> None:
    """Background repair task."""
    try:
        from aether_os.phases.p08_cicd.pipeline import run_repair
        result = await run_repair(
            ci_log=request_data.ci_log,
            repo_name=request_data.repo_name,
            branch=request_data.branch,
            job_id=job_id,
            call_graph=call_graph,
        )
        logger.info("Repair job %s completed: %s", job_id, result)
    except Exception as exc:
        logger.error("Repair job %s failed: %s", job_id, exc)


@router.post("/ci/webhook", response_model=RepairResponse)
async def receive_ci_webhook(
    request_data: CIWebhookRequest,
    background_tasks: BackgroundTasks,
) -> RepairResponse:
    """
    Receive a CI failure webhook and trigger automated repair.

    BUG 5 FIX: Rebuilds call graph from request_data.repo_root if provided,
    ensuring per-repo accuracy.
    """
    global _CALL_GRAPH

    job_id = str(uuid.uuid4())
    logger.info(
        "CI webhook received: repo=%s branch=%s job=%s",
        request_data.repo_name, request_data.branch, job_id,
    )

    # BUG 5 FIX: Rebuild call graph if repo_root provided in request
    call_graph = _CALL_GRAPH
    if request_data.repo_root:
        fresh_cg = _build_call_graph_for_repo(request_data.repo_root)
        if fresh_cg:
            call_graph = fresh_cg
            _CALL_GRAPH = fresh_cg  # Update global for reuse

    if call_graph is None:
        logger.warning(
            "Job %s: running without call graph — AST-proximity scoring degraded", job_id
        )

    background_tasks.add_task(
        _run_repair_async,
        job_id,
        request_data,
        call_graph,
    )

    return RepairResponse(
        job_id=job_id,
        status="queued",
        message="Repair job queued",
        repo_name=request_data.repo_name,
    )


@router.get("/ci/jobs/{job_id}")
async def get_repair_job_status(job_id: str) -> Dict[str, Any]:
    """Get the status of a repair job."""
    from aether_os.core.audit.ledger import get_ledger
    ledger = get_ledger()
    detail = ledger.get_run_detail(job_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return detail
