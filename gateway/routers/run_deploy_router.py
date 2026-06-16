"""
AetherOS — Run Deploy Router
==============================
Handles deployment, artifacts, downloads, GitHub push, spec management, and chat.

Routes
------
  POST /factory/runs/{run_id}/deploy
  DELETE /factory/runs/{run_id}/deploy        (stop-deployment)
  GET  /factory/runs/{run_id}/artifacts
  GET  /factory/runs/{run_id}/download
  POST /factory/runs/{run_id}/push-github
  GET  /factory/runs/{run_id}/traces
  GET  /factory/runs/{run_id}/traces/{trace_id}
  GET  /factory/runs/{run_id}/frontend-spec
  POST /factory/runs/{run_id}/frontend-spec
  GET  /factory/runs/{run_id}/backend-spec
  POST /factory/runs/{run_id}/backend-spec
  POST /factory/runs/{run_id}/chat

Independently importable — no imports from factory_runs_router.
"""
from __future__ import annotations

import logging
import re as _re_art
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from aether_os.gateway.dependencies import get_current_user

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
    from aether_os.core.audit.ledger import get_ledger
    from aether_os.core.db_utils import async_update_run_live_url
    import subprocess as _sp
    import asyncio as _aio

    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    def _docker_check():
        try:
            return _sp.run(["docker", "info"], capture_output=True, timeout=10)
        except Exception:
            return None

    check = await _aio.to_thread(_docker_check)
    if check is None or check.returncode != 0:
        logger.warning(
            "Docker unavailable for run %s — falling back to in-process preview", run_id
        )
        # Delegate to run_app_router (no circular dep: run_app_router has no dep on this file)
        from aether_os.gateway.routers.run_app_router import start_run_app
        await start_run_app(run_id=run_id, user=user)
        return {
            "success": True,
            "live_url": "/app-preview/",
            "mode": "preview",
            "message": "Docker unavailable — using in-process preview",
        }

    from types import SimpleNamespace
    from aether_os.phases.p11_deployment.task_agent import TaskAgent

    def _run_agent():
        import asyncio
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
    from aether_os.core.audit.ledger import get_ledger
    from aether_os.core.db_utils import async_update_run_live_url
    import subprocess as _sp
    import asyncio as _aio

    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    container_name = f"aetheros-app-{run_id[:8]}"

    def _docker_check_stop():
        try:
            return _sp.run(["docker", "info"], capture_output=True, timeout=10)
        except Exception:
            return None

    docker_check = await _aio.to_thread(_docker_check_stop)
    if docker_check is None or docker_check.returncode != 0:
        logger.warning(
            "Docker unavailable for stop of run %s — stopping in-process preview", run_id
        )
        from aether_os.gateway.routers.run_app_router import stop_run_app
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
    from pathlib import Path
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select
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
        for fpath in sorted(project_dir.rglob("*")):
            if not fpath.is_file():
                continue
            rel = fpath.relative_to(project_dir)
            rel_str = str(rel)
            parts = rel.parts
            if any(p in _ARTIFACT_SKIP for p in parts):
                continue
            if fpath.name == "run_app.log" and not _is_superadmin:
                continue
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
                "size_bytes": fpath.stat().st_size,
                "created_at": int(fpath.stat().st_mtime * 1000),
            })
    return artifacts


@router.get("/factory/runs/{run_id}/download")
async def download_run_zip(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """Download all run artifacts as a ZIP."""
    import io
    import zipfile
    from pathlib import Path
    from fastapi.responses import StreamingResponse
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select

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

    _SKIP = {
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        "node_modules", ".git", ".venv", "venv", ".aetheros",
    }
    _ALLOW_HIDDEN = {
        ".env.example", ".gitignore", ".dockerignore", ".eslintrc",
        ".prettierrc", ".editorconfig", ".nvmrc",
    }
    _ALLOW_HIDDEN_DIRS = {".github", ".devcontainer"}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in sorted(project_dir.rglob("*")):
            if not fpath.is_file():
                continue
            rel = fpath.relative_to(project_dir)
            if rel.name == "run_preview.py":
                continue
            parts = rel.parts
            if any(p in _SKIP for p in parts):
                continue
            if any(p.startswith(".") for p in parts):
                if not (parts[0] in _ALLOW_HIDDEN_DIRS or fpath.name in _ALLOW_HIDDEN):
                    continue
            if fpath.suffix in {".pyc", ".pyo", ".db", ".db-shm", ".db-wal", ".log"}:
                continue
            try:
                if fpath.stat().st_size > 5 * 1024 * 1024:
                    continue
            except OSError:
                continue
            zf.write(fpath, rel)
    buf.seek(0)
    name = (run.project_name or run_id).replace(" ", "_")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


@router.post("/factory/runs/{run_id}/push-github")
async def push_run_to_github(
    run_id: str,
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """Push the generated project to a new GitHub repository."""
    import base64
    import httpx
    from pathlib import Path
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select

    github_token = req.get("github_token", "")
    repo_name = req.get("repo_name", "")
    if not github_token or not repo_name:
        raise HTTPException(status_code=422, detail="github_token and repo_name are required")

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

    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    _SKIP = {"__pycache__", ".pytest_cache", "node_modules", ".git", ".venv", "venv"}
    _ALLOW_HIDDEN = {
        ".env.example", ".gitignore", ".dockerignore", ".eslintrc",
        ".prettierrc", ".editorconfig", ".nvmrc",
    }
    _ALLOW_HIDDEN_DIRS = {".github", ".devcontainer"}

    async with httpx.AsyncClient(timeout=30) as gh:
        create_res = await gh.post(
            "https://api.github.com/user/repos",
            json={
                "name": repo_name,
                "description": "Generated by AetherOS Factory",
                "private": False,
                "auto_init": False,
            },
            headers=headers,
        )
        if create_res.status_code not in (201, 422):
            raise HTTPException(
                status_code=502,
                detail=f"GitHub repo creation failed: {create_res.text}",
            )
        repo_data = create_res.json()
        html_url = repo_data.get("html_url", f"https://github.com/user/{repo_name}")
        user_res = await gh.get("https://api.github.com/user", headers=headers)
        gh_user = user_res.json().get("login", "aetheros")

        files_pushed = 0
        for fpath in sorted(project_dir.rglob("*")):
            if not fpath.is_file() or files_pushed >= 50:
                break
            rel = fpath.relative_to(project_dir)
            if rel.name == "run_preview.py":
                continue
            parts = rel.parts
            if any(p in _SKIP for p in parts):
                continue
            if any(p.startswith(".") for p in parts):
                if not (parts[0] in _ALLOW_HIDDEN_DIRS or fpath.name in _ALLOW_HIDDEN):
                    continue
            if fpath.suffix in {".pyc", ".pyo"}:
                continue
            try:
                content = base64.b64encode(fpath.read_bytes()).decode()
                await gh.put(
                    f"https://api.github.com/repos/{gh_user}/{repo_name}/contents/{rel}",
                    json={"message": f"Add {rel}", "content": content},
                    headers=headers,
                )
                files_pushed += 1
            except Exception:
                continue

    return {"html_url": html_url, "files_pushed": files_pushed}


@router.get("/factory/runs/{run_id}/traces")
async def get_run_traces(
    run_id: str,
    phase: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    user: Dict[str, Any] = _current_user(),
):
    """Return LLM call traces for a pipeline run."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import LLMTrace
    from sqlalchemy import select

    sf = get_session_factory()
    async with sf() as db:
        q = select(LLMTrace).where(LLMTrace.run_id == run_id)
        if phase:
            q = q.where(LLMTrace.phase == phase)
        q = q.order_by(LLMTrace.created_at.asc()).limit(limit)
        result = await db.execute(q)
        traces = result.scalars().all()

    return [
        {
            "id": t.id,
            "phase": t.phase,
            "task_type": t.task_type,
            "model": t.model,
            "attempt": t.attempt,
            "duration_ms": t.duration_ms,
            "tokens_in": t.tokens_in,
            "tokens_out": t.tokens_out,
            "parsed_ok": t.parsed_ok,
            "error": t.error,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "has_prompt": bool(t.prompt),
            "has_response": bool(t.raw_response),
        }
        for t in traces
    ]


@router.get("/factory/runs/{run_id}/traces/{trace_id}")
async def get_trace_detail(
    run_id: str,
    trace_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """Return full prompt and response for a single trace."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import LLMTrace
    from sqlalchemy import select

    sf = get_session_factory()
    async with sf() as db:
        result = await db.execute(
            select(LLMTrace).where(
                LLMTrace.id == trace_id,
                LLMTrace.run_id == run_id,
            )
        )
        trace = result.scalar_one_or_none()
        if not trace:
            raise HTTPException(status_code=404, detail="Trace not found")

    return {
        "id": trace.id,
        "phase": trace.phase,
        "task_type": trace.task_type,
        "model": trace.model,
        "prompt": trace.prompt,
        "raw_response": trace.raw_response,
        "parsed_ok": trace.parsed_ok,
        "error": trace.error,
        "attempt": trace.attempt,
        "duration_ms": trace.duration_ms,
        "tokens_in": trace.tokens_in,
        "tokens_out": trace.tokens_out,
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
    }


@router.get("/factory/runs/{run_id}/frontend-spec")
async def get_frontend_spec(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """Retrieve the frontend spec attached to a run."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import RunSpec, Run
    sf = get_session_factory()
    async with sf() as session:
        run = await session.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        row = await session.get(RunSpec, (run_id, "frontend"))
    return {"spec": row.spec if row else {}}


@router.post("/factory/runs/{run_id}/frontend-spec")
async def save_frontend_spec(
    run_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """Save / overwrite the frontend spec for a run."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import RunSpec, Run
    spec = body.get("spec") or body
    sf = get_session_factory()
    async with sf() as session:
        run = await session.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        row = await session.get(RunSpec, (run_id, "frontend"))
        if row:
            row.spec = spec
            row.updated_at = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            )
        else:
            session.add(RunSpec(run_id=run_id, spec_type="frontend", spec=spec))
        await session.commit()
    return {"status": "saved"}


@router.get("/factory/runs/{run_id}/backend-spec")
async def get_backend_spec(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
):
    """Retrieve the backend spec attached to a run."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import RunSpec, Run
    sf = get_session_factory()
    async with sf() as session:
        run = await session.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        row = await session.get(RunSpec, (run_id, "backend"))
    return {"spec": row.spec if row else {}}


@router.post("/factory/runs/{run_id}/backend-spec")
async def save_backend_spec(
    run_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """Save / overwrite the backend spec for a run."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import RunSpec, Run
    spec = body.get("spec") or body
    sf = get_session_factory()
    async with sf() as session:
        run = await session.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        row = await session.get(RunSpec, (run_id, "backend"))
        if row:
            row.spec = spec
            row.updated_at = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            )
        else:
            session.add(RunSpec(run_id=run_id, spec_type="backend", spec=spec))
        await session.commit()
    return {"status": "saved"}


@router.post("/factory/runs/{run_id}/chat")
async def project_chat(
    run_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """Project-scoped conversational AI endpoint."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from aether_os.core.services import learning_service
    from aether_os.core.llm.client import LLMClient

    message = (body.get("message") or "").strip()
    history = body.get("history", [])
    if not message:
        raise HTTPException(status_code=400, detail="message required")

    sf = get_session_factory()
    async with sf() as session:
        run = await session.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        user_ctx = await learning_service.get_user_context(
            org_id=user["org_id"], user_id=user["user_id"], session=session
        )
        project_name = run.project_name or run_id

    system_prompt = (
        "You are AetherOS, an autonomous software development assistant.\n\n"
        "SCOPE RESTRICTION — ABSOLUTE:\n"
        "You may ONLY discuss topics directly related to the current project:\n"
        "1. Software requirements and specifications\n"
        "2. Architecture, design patterns, and technical decisions\n"
        "3. Code review, debugging, and error analysis\n"
        "4. Testing strategy and coverage\n"
        "5. Deployment, infrastructure, and monitoring\n"
        "6. Performance optimization\n"
        "7. Security review of generated code\n"
        "8. Documentation and API specifications\n"
        "9. Change requests and iterations\n"
        "10. Project planning and timeline estimation\n\n"
        'You MUST refuse all other topics with: "I\'m focused on your project. '
        "Let's talk about [specific project topic]. "
        'What aspect of the project can I help you with?"\n\n'
        f"Current project: {project_name}\n"
        f"User's learned preferences: {user_ctx}"
    )

    conversation = []
    for h in history[-10:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            conversation.append({"role": h["role"], "content": h["content"]})
    conversation.append({"role": "user", "content": message})

    try:
        client = LLMClient()
        reply = await client.call(
            prompt=message,
            task_type="code_generation",
            system=system_prompt,
            max_tokens=2048,
        )
    except Exception as e:
        logger.warning("Chat LLM call failed: %s", e)
        reply = "I'm having trouble connecting right now. Please try again shortly."

    return {"reply": reply, "run_id": run_id, "project": project_name}
