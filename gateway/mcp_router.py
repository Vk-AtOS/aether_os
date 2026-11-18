"""
AetherOS — MCP REST Router
Exposes MCP tool functionality as simple REST endpoints mounted at /mcp.
Runs on the same port as the main app (8000) — no separate MCP server needed.
"""
from __future__ import annotations

import json
import uuid
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.models import PhaseCompletion, Run
from aether_os.core.run_app import safe_fs
from aether_os.gateway.dependencies import get_current_user as _get_current_user, require_run_user
from aether_os.gateway.policy_guard import admit_run_start

logger = logging.getLogger(__name__)


# Auth: the shared get_current_user (revocation, is_active, token-type checks) —
# MCP used to decode the JWT itself and skipped all of them.


router = APIRouter(prefix="/mcp", tags=["MCP"])


@router.get("/list_runs")
async def mcp_list_runs(
    user: Dict[str, Any] = Depends(_get_current_user),
) -> List[Dict[str, Any]]:
    """List all factory runs for the authenticated org."""
    org_id = user.get("org_id")
    async with get_session_factory()() as db:
        rows = (await db.execute(
            select(Run.id, Run.status, Run.command, Run.started_at, Run.finished_at)
            .where(Run.org_id == org_id).order_by(Run.started_at.desc()).limit(100))).all()
    return [dict(r._mapping) for r in rows]


@router.get("/get_run_status/{run_id}")
async def mcp_get_run_status(
    run_id: str,
    user: Dict[str, Any] = Depends(require_run_user),
) -> List[Dict[str, Any]]:
    """Get phase-by-phase status of a run."""
    async with get_session_factory()() as db:
        rows = (await db.execute(
            select(PhaseCompletion.phase_name, PhaseCompletion.status, PhaseCompletion.updated_at)
            .where(PhaseCompletion.run_id == run_id).order_by(PhaseCompletion.updated_at))).all()
    return [dict(r._mapping) for r in rows]


@router.get("/get_artifact/{run_id}")
async def mcp_get_artifact(
    run_id: str,
    file_path: str,
    user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, Any]:
    """Retrieve a generated artifact file for a run (file_path query param)."""
    project_dir = Path.home() / ".aether_os" / "projects" / run_id
    full_path = (project_dir / file_path).resolve()
    if not full_path.is_relative_to(project_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid file path")
    # safe_fs: the sandboxed app writes here; a link anywhere on the path is a 404.
    content = safe_fs.read_text_or_none(project_dir, full_path)
    if content is not None:
        return {"run_id": run_id, "file_path": file_path, "content": content}
    raise HTTPException(status_code=404, detail=f"Artifact {file_path} not found for run {run_id}")


class StartPipelineRequest(BaseModel):
    requirement: str
    project_name: Optional[str] = None


@router.post("/start_pipeline")
async def mcp_start_pipeline(
    req: StartPipelineRequest,
    user: Dict[str, Any] = Depends(_get_current_user),
) -> Dict[str, Any]:
    """Start a new factory pipeline run."""
    import asyncio
    from aether_os.orchestrator.factory_pipeline import get_factory
    org_id = user.get("org_id")
    await admit_run_start(user)  # policy + trial allowance, same gate as /factory/start
    run_id = str(uuid.uuid4())
    factory = get_factory()
    asyncio.create_task(factory.run(
        client_id="mcp",
        raw_input=req.requirement,
        org_id=org_id,
        run_id=run_id,
    ))
    return {"run_id": run_id, "status": "started", "message": "Pipeline started"}


@router.get("/get_architecture/{run_id}")
async def mcp_get_architecture(
    run_id: str,
    user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, Any]:
    """Retrieve the architecture document for a run."""
    project_dir = Path.home() / ".aether_os" / "projects" / run_id
    for candidate in [
        "p02_architecture/architecture.json",
        "architecture.json",
        "p02_architecture/architecture.md",
    ]:
        content = safe_fs.read_text_or_none(project_dir, candidate)
        if content is not None:
            try:
                return {"run_id": run_id, "architecture": json.loads(content)}
            except json.JSONDecodeError:
                return {"run_id": run_id, "architecture": content}
    raise HTTPException(status_code=404, detail=f"Architecture not found for run {run_id}")
