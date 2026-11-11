
from __future__ import annotations
import datetime
import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel

from aether_os.gateway.client_portal.provenance import _build_provenance

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/portal", tags=["client-portal"])


class FeedbackBody(BaseModel):
    feedback: str
    phase: Optional[str] = None


class ApproveBody(BaseModel):
    approved: bool
    comment: Optional[str] = None


def _get_portal_token(project_id: str) -> str:
    """Return (or generate) a persistent portal access token for a run, stored next to the project."""
    import secrets
    from aether_os.core.projects import get_project_manager
    try:
        project_dir = get_project_manager().get_project_dir(project_id)
        token_file = project_dir / ".portal_token"
        if token_file.exists():
            return token_file.read_text().strip()
        token = secrets.token_urlsafe(32)
        project_dir.mkdir(parents=True, exist_ok=True)
        token_file.write_text(token)
        return token
    except Exception as exc:
        logger.debug("Failed to get/create portal token for project %s: %s", project_id, exc)
        return ""


async def _portal_auth(request: Request, portal_token: Optional[str] = None) -> None:
    """
    Lightweight portal auth for write endpoints (approve / feedback).
    Accepts either:
      - A valid AetherOS JWT in the Authorization: Bearer header (dashboard users)
      - An X-Portal-Token header matching the run's stored portal token file
      - A ?portal_token=<uuid> query param (legacy; prefer header to avoid URL log exposure)
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        jwt_val = auth_header[7:]
        try:
            from aether_os.gateway.auth import decode_bearer_token
            payload = decode_bearer_token(jwt_val)
            if payload and payload.get("org_id"):
                return  # Valid JWT
        except Exception as exc:
            logger.debug("Portal JWT validation failed, falling through to portal token check: %s", exc)

    # Prefer header-supplied token over query param to keep token out of server logs
    effective_token = request.headers.get("x-portal-token") or portal_token
    if effective_token:
        # Extract project_id from request path to validate the token
        path = request.url.path
        parts = path.strip("/").split("/")
        # Path is /portal/{project_id}/approve or /portal/{project_id}/feedback
        if len(parts) >= 2 and parts[0] == "portal":
            stored = _get_portal_token(parts[1])
            if stored and stored == effective_token:
                return  # Valid portal token

    raise HTTPException(status_code=401, detail="Portal authentication required")


async def _resolve_run(project_id: str) -> dict:
    """
    Resolve a project/run by ID. First tries the SQLAlchemy DB (factory runs),
    then falls back to the file-based ProjectManager index.
    Returns a normalized dict with keys: project_id, project_name, status, project_dir.
    """
    from pathlib import Path as _P

    # Primary: look up in factory runs DB
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import select
        sf = get_session_factory()
        async with sf() as session:
            run = (await session.execute(
                select(Run).where(Run.id == project_id)
            )).scalar_one_or_none()
        if run:
            project_dir = _P.home() / ".aether_os" / "projects" / project_id
            return {
                "project_id": project_id,
                "project_name": run.project_name,
                "status": run.status,
                "client_id": run.client_id or "",
                "project_dir": project_dir,
                "metadata": {},
            }
    except Exception as exc:
        logger.debug("DB run lookup failed: %s", exc)

    # Fallback: file-based ProjectManager
    from aether_os.core.projects import get_project_manager
    pm = get_project_manager()
    project = pm.get_project(project_id)
    if project:
        return {
            "project_id": project_id,
            "project_name": project.name,
            "status": "completed",
            "client_id": project.client_id,
            "project_dir": pm.get_project_dir(project_id),
            "metadata": project.metadata,
        }

    raise HTTPException(404, f"Project {project_id} not found")


@router.get("/{project_id}/status")
async def get_project_status(project_id: str):
    try:
        rec = await _resolve_run(project_id)
        project_dir = rec["project_dir"]
        phases_completed = []
        if project_dir.exists():
            for phase_dir in sorted(project_dir.iterdir()):
                if phase_dir.is_dir() and phase_dir.name.startswith("p"):
                    phases_completed.append(phase_dir.name)

        # Extract requirements text from p01 intake output
        requirement_text = ""
        specification_text = ""
        try:
            p01_dir = project_dir / "p01_intake_requirements"
            # Try all known artifact locations written by p01
            intake_candidates = [
                p01_dir / "intake" / "intake.json",
                p01_dir / "requirements.json",
            ]
            for intake_json in intake_candidates:
                if intake_json.exists():
                    intake_data = json.loads(intake_json.read_text())
                    requirement_text = (
                        intake_data.get("raw_text") or
                        intake_data.get("description") or
                        intake_data.get("requirements_text") or
                        intake_data.get("structured_requirements") or ""
                    )
                    if requirement_text:
                        break

            # Fallback: read requirements.md directly
            if not requirement_text:
                md_candidates = [
                    p01_dir / "requirements.md",
                    p01_dir / "requirements" / "requirements.md",
                ]
                for req_md in md_candidates:
                    if req_md.exists():
                        requirement_text = req_md.read_text(encoding="utf-8")[:3000]
                        break

            specification_text = requirement_text
        except Exception as _re:
            logger.debug("Could not load intake data: %s", _re)

        # Best-effort compliance score from delivery JSON
        compliance_score = None
        try:
            delivery_json = project_dir / "p12_delivery" / "delivery.json"
            if delivery_json.exists():
                delivery_data = json.loads(delivery_json.read_text())
                compliance_score = delivery_data.get("compliance_score")
        except Exception as exc:
            logger.debug("Failed to load compliance_score from delivery.json for run %s: %s", project_id, exc)

        # Construct GitHub Codespaces deep-link if the run has a github_repo_url
        github_url = rec.get("metadata", {}).get("github_repo_url", "")
        codespaces_url = None
        if github_url and "github.com" in github_url:
            repo_path = github_url.replace("https://github.com/", "").rstrip("/")
            codespaces_url = (
                f"https://github.com/codespaces/new"
                f"?repo={repo_path}&machine=basicLinux32gb"
            )

        return {
            "project_id": project_id,
            "project_name": rec["project_name"],
            "status": rec["status"],
            "client_id": rec["client_id"],
            "phases_completed": phases_completed,
            "current_phase": phases_completed[-1] if phases_completed else None,
            "metadata": rec["metadata"],
            "requirements": [requirement_text] if requirement_text else [],
            "specification": specification_text,
            "download_url": f"/portal/{project_id}/download",
            "provenance_url": f"/portal/{project_id}/provenance",
            "compliance_score": compliance_score,
            "codespaces_url": codespaces_url,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Status error: %s", e)
        raise HTTPException(500, str(e))


@router.get("/{project_id}/phase/{phase_name}")
async def get_phase_output(project_id: str, phase_name: str):
    try:
        from aether_os.core.projects import get_project_manager
        pm = get_project_manager()
        phase_dir = pm.get_output_dir(project_id, phase_name)
        files = {}
        for f in phase_dir.rglob("*"):
            if f.is_file() and f.suffix in (".md", ".json", ".txt", ".yml", ".yaml"):
                try:
                    files[f.name] = f.read_text()[:5000]
                except Exception as exc:
                    logger.debug("Failed to read phase output file %s: %s", f.name, exc)
        return {"project_id": project_id, "phase": phase_name, "files": files}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/{project_id}/approve")
async def approve_phase(
    project_id: str,
    body: ApproveBody,
    _auth: None = Depends(_portal_auth),
):
    try:
        from aether_os.core.approval.store import get_approvals_store
        store = get_approvals_store()
        ticket_id = f"portal-{project_id}-approval"
        # Record the approval decision
        logger.info("Client approval for %s: approved=%s comment=%s",
                    project_id, body.approved, body.comment)
        return {"project_id": project_id, "approved": body.approved,
                "message": "Approval recorded. Next phase will start shortly." if body.approved
                           else "Change request noted. Re-running affected phases."}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/{project_id}/feedback")
async def submit_feedback(
    project_id: str,
    body: FeedbackBody,
    _auth: None = Depends(_portal_auth),
):
    try:
        import time
        rec = await _resolve_run(project_id)
        project_dir = rec["project_dir"]
        project_dir.mkdir(parents=True, exist_ok=True)
        feedback_file = project_dir / "feedback.jsonl"
        entry = {"timestamp": time.time(), "feedback": body.feedback, "phase": body.phase}
        with open(feedback_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return {"project_id": project_id, "message": "Feedback recorded", "entry": entry}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Download endpoints ────────────────────────────────────────────────────────

@router.get("/{run_id}/download")
async def portal_download_zip(run_id: str):
    """Download all project artifacts as a ZIP file.

    No auth required — the run_id UUID is unguessable and acts as the
    access token for client delivery.
    """
    rec = await _resolve_run(run_id)
    project_dir: Path = rec["project_dir"]

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project artifacts not found")

    # Build ZIP in memory
    buf = io.BytesIO()
    try:
        _SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv", ".mypy_cache",
                      ".pytest_cache", ".aetheros"}
        _SKIP_SUFFIXES = {".pyc", ".pyo", ".db", ".db-shm", ".db-wal", ".log"}
        # These hidden files/dirs are safe to include — clients need them for deployment
        _ALLOW_HIDDEN_FILES = {".env.example", ".gitignore", ".dockerignore", ".eslintrc",
                               ".prettierrc", ".editorconfig", ".nvmrc"}
        _ALLOW_HIDDEN_DIRS = {".github", ".devcontainer"}
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for file_path in project_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_path.name == "run_preview.py":
                    continue
                parts_set = set(file_path.parts)
                # Skip known heavy/sensitive/internal directories
                if parts_set & _SKIP_DIRS:
                    continue
                # Allow .github/ and .devcontainer/; allow known dotfiles; skip everything else hidden
                rel_parts = file_path.relative_to(project_dir).parts
                if any(part.startswith(".") for part in rel_parts):
                    if not (rel_parts[0] in _ALLOW_HIDDEN_DIRS or file_path.name in _ALLOW_HIDDEN_FILES):
                        continue
                # Skip byte-compiled and DB journal files
                if file_path.suffix in _SKIP_SUFFIXES:
                    continue
                # Skip files larger than 5 MB
                try:
                    if file_path.stat().st_size > 5 * 1024 * 1024:
                        continue
                except OSError:
                    continue
                try:
                    arcname = file_path.relative_to(project_dir)
                    zf.write(file_path, arcname)
                except Exception as fe:
                    logger.debug("Skipping %s in ZIP: %s", file_path, fe)

            # Embed provenance document
            provenance_md = _build_provenance(
                {
                    "project_name": rec.get("project_name", ""),
                    "domain": rec.get("metadata", {}).get("domain", "general"),
                    "phases": {},
                },
                run_id,
            )
            zf.writestr("BUILD_PROVENANCE.md", provenance_md)
    except Exception as exc:
        logger.error("ZIP assembly failed for run %s: %s", run_id, exc)
        raise HTTPException(status_code=500, detail="Failed to build ZIP archive")

    buf.seek(0)
    project_name = rec.get("project_name", run_id[:8]) or run_id[:8]
    safe_name = project_name.lower().replace(" ", "-").replace("/", "-")
    filename = f"{safe_name}-{run_id[:8]}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{run_id}/provenance")
async def portal_provenance(run_id: str):
    """Return the build provenance Markdown document."""
    rec = await _resolve_run(run_id)

    # Try to load richer run detail from the ledger (best-effort)
    run_detail: dict = {
        "project_name": rec.get("project_name", ""),
        "domain": rec.get("metadata", {}).get("domain", "general"),
        "phases": {},
    }
    try:
        from aether_os.core.audit.ledger import get_ledger
        ledger_detail = await get_ledger().async_get_run_detail(run_id, org_id=None)
        if ledger_detail:
            run_detail.update(ledger_detail)
    except Exception as exc:
        logger.debug("Ledger lookup for provenance failed: %s", exc)

    md = _build_provenance(run_detail, run_id)
    return Response(content=md, media_type="text/markdown")
