"""
AetherOS — Run Deploy Router
==============================
Handles deployment, artifacts, and ZIP downloads.
Routes
------
  POST /factory/runs/{run_id}/deploy
  DELETE /factory/runs/{run_id}/deploy        (stop-deployment)
  GET  /factory/runs/{run_id}/artifacts
  GET  /factory/runs/{run_id}/download
Independently importable — no imports from factory_runs_router.
See run_preview_router.py for push-github, traces, specs, and project chat.
"""
from __future__ import annotations
import logging
import re as _re_art
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from aether_os.core.project_export import ExportError, build_export_zip
from aether_os.core.run_app import safe_fs
from aether_os.gateway.dependencies import get_current_user
from aether_os.core.audit.ledger import get_ledger
from aether_os.core.db import get_session_factory
from aether_os.core.db_utils import async_update_run_live_url
from aether_os.core.models import Run
from aether_os.gateway.routers.run_app_router import start_run_app
from aether_os.gateway.routers.run_app_router import stop_run_app
from aether_os.phases.p11_deployment.task_agent import TaskAgent
from fastapi.responses import StreamingResponse
from pathlib import Path
from sqlalchemy import select
from types import SimpleNamespace
import asyncio
import asyncio as _aio
import subprocess as _sp
logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])
# ── Auth helper ────────────────────────────────────────────────────────────────
def _current_user():
    return Depends(get_current_user)
# ── Routes ─────────────────────────────────────────────────────────────────────
@router.post("/factory/runs/{run_id}/deploy")
async def deploy_run(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Manually trigger Docker deployment (non-blocking)."""
    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    def _docker_check():
        try:
            return _sp.run(["docker", "info"], capture_output=True, timeout=10)
        except Exception as e:
            logger.warning("run_deploy_router: docker check failed: %s", e)
            return None
    check = await _aio.to_thread(_docker_check)
    if check is None or check.returncode != 0:
        logger.warning(
            "Docker unavailable for run %s — falling back to in-process preview", run_id
        )
        # Delegate to run_app_router (no circular dep: run_app_router has no dep on this file)
        await start_run_app(run_id=run_id, user=user)
        return {
            "success": True,
            "live_url": "/app-preview/",
            "mode": "preview",
            "message": "Docker unavailable — using in-process preview",
        }
    def _run_agent():
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
    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    container_name = f"aetheros-app-{run_id[:8]}"
    def _docker_check_stop():
        try:
            return _sp.run(["docker", "info"], capture_output=True, timeout=10)
        except Exception as e:
            logger.warning("run_deploy_router: docker stop-check failed: %s", e)
            return None
    docker_check = await _aio.to_thread(_docker_check_stop)
    if docker_check is None or docker_check.returncode != 0:
        logger.warning(
            "Docker unavailable for stop of run %s — stopping in-process preview", run_id
        )
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
async def get_run_artifacts(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """List artifacts for a run."""
    sf = get_session_factory()
    async with sf() as session:
        run = (await session.execute(
            select(Run).where(Run.id == run_id, Run.org_id == user["org_id"])
        )).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    project_dir = Path.home() / ".aether_os" / "projects" / run_id
    artifacts = []
    _ARTIFACT_SKIP = {
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        "node_modules", ".git", ".venv", "venv", ".aetheros",
    }
    _ALLOW_HIDDEN = {
        ".env.example", ".gitignore", ".dockerignore", ".eslintrc",
        ".prettierrc", ".editorconfig", ".nvmrc",
    }
    _ALLOW_HIDDEN_DIRS = {".github", ".devcontainer"}
    _is_superadmin = user.get("role") == "superadmin"
    def _relative_artifact_path(rel_str: str) -> str:
        _stripped = _re_art.sub(r"^.*?backend_codegen/src/", "src/", rel_str)
        if _stripped == rel_str:
            _stripped = _re_art.sub(r"^p\d+[^/]*/(?:backend_codegen/)?src/", "src/", rel_str)
        return _stripped
    if project_dir.exists():
        # safe_fs: the sandboxed app writes here, so links are never entered or followed.
        for rel in safe_fs.walk_files(project_dir, skip_dirs=_ARTIFACT_SKIP):
            fpath = project_dir / rel
            st = safe_fs.stat_or_none(project_dir, rel)
            if st is None:
                continue
            rel_str = str(rel)
            parts = rel.parts
            if any(p in _ARTIFACT_SKIP for p in parts):
                continue
            if fpath.name == "run_app.log":
                # Allow superadmin OR the org owner/admin who owns this run
                if not _is_superadmin:
                    _run_org_id = getattr(run, "org_id", None)
                    _user_org_id = user.get("org_id")
                    _user_role = user.get("role", "")
                    if _run_org_id != _user_org_id or _user_role not in ("owner", "admin"):
                        continue
                    # else: org owner/admin can see their own run's log
            if any(p.startswith(".") for p in parts):
                if not (parts[0] in _ALLOW_HIDDEN_DIRS or fpath.name in _ALLOW_HIDDEN):
                    continue
            if fpath.suffix in {".pyc", ".pyo"}:
                continue
            _display_path = _relative_artifact_path(rel_str)
            artifacts.append({
                "filename": fpath.name,
                "path": _display_path,
                "phase": rel.parts[0] if len(rel.parts) > 1 else "root",
                "size_bytes": st.st_size,
                "created_at": int(st.st_mtime * 1000),
            })
    return artifacts
@router.get("/factory/runs/{run_id}/download")
async def download_run_zip(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """Download all run artifacts as a ZIP."""
    sf = get_session_factory()
    async with sf() as session:
        run = (await session.execute(
            select(Run).where(Run.id == run_id, Run.org_id == user["org_id"])
        )).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    project_dir = Path.home() / ".aether_os" / "projects" / run_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project files not found")
    name = (run.project_name or run_id).replace(" ", "_")
    # The clean export (KAN-268): backend/ frontend/ compose, CI, README, manifest; no keys, .env, stage folders.
    try:
        buf, _manifest = await _aio.to_thread(build_export_zip, project_dir, name)
    except ExportError as e:
        raise HTTPException(status_code=422, detail={"message": str(e), "findings": [str(f) for f in e.findings]}) from e
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )