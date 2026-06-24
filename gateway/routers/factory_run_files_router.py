"""
AetherOS — Factory Run Files Router

Routes (file management, snapshots, env vars, VS Code):
  GET   /factory/runs/{run_id}/files
  GET   /factory/runs/{run_id}/file-content
  PATCH /factory/runs/{run_id}/file-content
  POST  /factory/runs/{run_id}/open-in-vscode
  GET   /factory/runs/{run_id}/envvars
  PATCH /factory/runs/{run_id}/envvars
  GET   /factory/runs/{run_id}/snapshots
  GET   /factory/runs/{run_id}/snapshots/{snapshot_id}
  POST  /factory/runs/{run_id}/memory/changelog
"""
from __future__ import annotations

import logging
import os
import pathlib
import tempfile
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["run-files"])


# ── Pydantic models ────────────────────────────────────────────────────────────

class FileWriteBody(BaseModel):
    path: str
    content: str


class EnvVarItem(BaseModel):
    key: str
    value: str


class EnvVarsBody(BaseModel):
    vars: List[EnvVarItem]


# ── Auth helper ────────────────────────────────────────────────────────────────

def _current_user():
    return Depends(get_current_user)


# ── Module-level constants ─────────────────────────────────────────────────────

_LANG_MAP = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".json": "json",
    ".yaml": "yaml", ".yml": "yaml", ".md": "markdown",
    ".sh": "bash", ".toml": "toml", ".html": "html",
    ".css": "css", ".diff": "diff",
}


async def _resolve_project_dir(run_id: str, org_id: str):
    """Return (run_detail, root_dir) or raise 404 — shared by file endpoints."""
    from aether_os.core.projects import get_project_manager
    from aether_os.core.audit.ledger import get_ledger

    run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not run_detail:
        raise HTTPException(status_code=404, detail="Run not found")
    project_id = run_detail.get("project_id", run_id)
    root_dir = get_project_manager().get_project_dir(project_id)
    return run_detail, root_dir


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/factory/runs/{run_id}/files")
async def get_run_files(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Recursive file tree for a run's output directory."""
    _, root_dir = await _resolve_project_dir(run_id, user.get("org_id"))
    if not root_dir.exists():
        return {"run_id": run_id, "tree": []}

    def build_tree(current_path: pathlib.Path, base_path: pathlib.Path) -> List[Dict]:
        items = []
        for item in sorted(current_path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
            if item.name.startswith("."):
                continue
            rel_path = str(item.relative_to(base_path))
            if item.is_dir():
                items.append({
                    "name": item.name, "type": "directory",
                    "path": rel_path, "children": build_tree(item, base_path),
                })
            else:
                items.append({
                    "name": item.name, "type": "file",
                    "path": rel_path, "size_bytes": item.stat().st_size,
                    "extension": item.suffix,
                })
        return items

    return {"run_id": run_id, "tree": build_tree(root_dir, root_dir)}


def _safe_file_path(root_dir: pathlib.Path, path: str) -> pathlib.Path:
    """Sanitise a user-supplied path and resolve it inside root_dir.

    Raises HTTPException 403 on path traversal attempts.
    """
    # Strip leading slashes to prevent absolute path injection
    safe_relative = (
        pathlib.Path(path.lstrip("/")).resolve().relative_to(pathlib.Path("/").resolve())
        if path.startswith("/")
        else pathlib.Path(path)
    )
    file_path = (root_dir / safe_relative).resolve()
    try:
        file_path.relative_to(root_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal detected")
    return file_path


@router.get("/factory/runs/{run_id}/file-content")
async def get_file_content(
    run_id: str,
    path: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Read file content from the run's project directory."""
    _, root_dir = await _resolve_project_dir(run_id, user.get("org_id"))
    file_path = _safe_file_path(root_dir.resolve(), path)

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    ext = file_path.suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg"):
        return {"path": path, "type": "image", "message": "Image files cannot be previewed"}

    language = _LANG_MAP.get(ext, "text")
    size = file_path.stat().st_size
    truncated = False
    content = ""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            if size > 1_000_000:
                content = f.read(50_000)
                truncated = True
            else:
                content = f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {e}")

    return {
        "path": path, "content": content, "language": language,
        "size_bytes": size, "truncated": truncated,
        "type": "diff" if ext == ".diff" else "text",
    }


@router.patch("/factory/runs/{run_id}/file-content")
async def patch_file_content(
    run_id: str,
    body: FileWriteBody,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Write content to a file in the project directory."""
    if user.get("role") == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot write files")
    _, root_dir = await _resolve_project_dir(run_id, user.get("org_id"))
    file_path = _safe_file_path(root_dir.resolve(), body.path)

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(body.content, encoding="utf-8")
        # Post-write baseline update for Guardian
        try:
            from aether_os.core.guardian.threat_detector import get_threat_detector
            await get_threat_detector().update_baseline(file_path)
        except Exception as e:
            logger.warning("Guardian: failed to update baseline after file write: %s", e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing file: {e}")

    return {"run_id": run_id, "path": body.path, "size": file_path.stat().st_size}


@router.post("/factory/runs/{run_id}/open-in-vscode")
async def open_in_vscode(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Open the project folder in VS Code on the local machine."""
    import subprocess as _sp

    _, root_dir = await _resolve_project_dir(run_id, user.get("org_id"))
    try:
        _sp.run(["code", str(root_dir.resolve())], check=False, capture_output=True)
        return {"opened": True, "path": str(root_dir.resolve())}
    except FileNotFoundError:
        return {"opened": False, "error": "VS Code CLI (code) not found in PATH"}


@router.get("/factory/runs/{run_id}/envvars")
async def get_envvars(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Read the .env (or .env.example) file from the project root."""
    _, root_dir = await _resolve_project_dir(run_id, user.get("org_id"))
    root_dir = root_dir.resolve()

    env_path = root_dir / ".env"
    source = ".env"
    if not env_path.exists():
        for _candidate, _src in [
            (root_dir / ".env.example", ".env.example"),
            (root_dir / "p04_backend" / "backend_codegen" / ".env", ".env"),
            (root_dir / "p04_backend" / "backend_codegen" / ".env.example", ".env.example"),
        ]:
            if _candidate.exists():
                env_path = _candidate
                source = _src
                break

    vars_list: List[Dict[str, str]] = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                k, _, v = stripped.partition("=")
                vars_list.append({"key": k.strip(), "value": v.strip()})

    return {"run_id": run_id, "vars": vars_list, "source": source}


@router.patch("/factory/runs/{run_id}/envvars")
async def patch_envvars(
    run_id: str,
    body: EnvVarsBody,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Write a .env file in the project root from the given key-value pairs."""
    if user.get("role") == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot write env vars")
    _, root_dir = await _resolve_project_dir(run_id, user.get("org_id"))
    env_path = root_dir.resolve() / ".env"

    lines = [f"{item.key}={item.value}" for item in body.vars]
    try:
        fd, tmp_name = tempfile.mkstemp(dir=env_path.parent, prefix=".env.tmp.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(tmp_name, env_path)
        except Exception as exc:
            logger.debug(
                "Failed to write env vars to tmp file for run %s, cleaning up: %s", run_id, exc,
            )
            os.unlink(tmp_name)
            raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing .env: {e}")

    return {"run_id": run_id, "written": len(body.vars)}


@router.get("/factory/runs/{run_id}/snapshots")
async def list_run_snapshots(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """List all code snapshots for a run (versioned file history)."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run, Snapshot
    from sqlalchemy import select as _sel

    sf = get_session_factory()
    async with sf() as sess:
        run = await sess.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        rows = (
            await sess.execute(
                _sel(Snapshot)
                .where(Snapshot.run_id == run_id)
                .order_by(Snapshot.created_at.desc())
            )
        ).scalars().all()
    return {
        "run_id": run_id,
        "snapshots": [
            {"id": s.id, "file_path": s.file_path, "created_at": s.created_at}
            for s in rows
        ],
    }


@router.get("/factory/runs/{run_id}/snapshots/{snapshot_id}")
async def get_run_snapshot(
    run_id: str,
    snapshot_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get full content of a specific code snapshot."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run, Snapshot

    sf = get_session_factory()
    async with sf() as sess:
        run = await sess.get(Run, run_id)
        if not run or run.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="Run not found")
        snap = await sess.get(Snapshot, snapshot_id)
        if not snap or snap.run_id != run_id:
            raise HTTPException(status_code=404, detail="Snapshot not found")
    return {
        "id": snap.id,
        "run_id": snap.run_id,
        "file_path": snap.file_path,
        "content": snap.content,
        "created_at": snap.created_at,
    }


@router.post("/factory/runs/{run_id}/memory/changelog")
async def add_changelog(
    run_id: str,
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Add entry to project changelog."""
    from aether_os.core.memory.memory_manager import MemoryManager
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select
    from pathlib import Path

    session_factory = get_session_factory()
    async with session_factory() as session:
        # B2: filter by org_id to prevent IDOR cross-tenant access
        stmt = select(Run).where(Run.id == run_id, Run.org_id == user["org_id"])
        run = (await session.execute(stmt)).scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404)

        project_dir = Path.home() / ".aether_os" / "projects" / run_id
        MemoryManager.add_changelog_entry(project_dir, req["entry"], user["sub"])
        return {"status": "ok"}
