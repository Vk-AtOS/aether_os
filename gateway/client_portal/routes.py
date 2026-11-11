from __future__ import annotations
import io
import json
import logging
import re
import secrets
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from aether_os.core.projects import get_project_manager
from aether_os.gateway.client_portal.provenance import _build_provenance
from aether_os.gateway.dependencies import assert_run_in_org, get_current_user, security_scheme

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


# A run / project id as a single safe path component: these ids are joined onto the
# projects directory, so "..", separators and empty values must never get that far.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _stored_portal_token(project_id: str) -> str:
    """Read the project's portal token without creating anything; "" if there is none."""
    try:
        token_file = get_project_manager()._root / project_id / ".portal_token"
        return token_file.read_text().strip() if token_file.is_file() else ""
    except Exception as exc:
        logger.warning("Could not read portal token for project %s: %s", project_id, exc)
        return ""


async def _portal_auth(
    request: Request,
    portal_token: Optional[str] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> None:
    """Auth for every /portal/{id}/... route. Accepts either:
      - the project's own portal token: X-Portal-Token header, or ?portal_token=
        (query form kept for plain download links; it does end up in access logs)
      - a signed-in user (or API key) of the organisation that owns the run.
    A valid session from another organisation is not enough: 404, same as any
    other run route, so run ids cannot be probed.
    """
    project_id = request.path_params.get("project_id") or request.path_params.get("run_id") or ""
    if not _SAFE_NAME.match(project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    supplied = request.headers.get("x-portal-token") or portal_token
    if supplied:
        stored = _stored_portal_token(project_id)
        if stored and secrets.compare_digest(stored.encode(), supplied.encode()):
            return
        raise HTTPException(status_code=401, detail="Portal authentication required")

    if credentials is None:
        raise HTTPException(status_code=401, detail="Portal authentication required")
    user = await get_current_user(request, credentials)
    await assert_run_in_org(project_id, user)


def _portal_error(what: str, project_id: str, exc: Exception) -> HTTPException:
    """Log the real error; the portal is client-facing, so the reply carries no
    exception text (it used to include import errors and filesystem paths)."""
    logger.warning("Portal %s failed for project %s: %s: %s", what, project_id, type(exc).__name__, exc)
    return HTTPException(status_code=500, detail=f"Portal {what} request failed")


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
async def get_project_status(project_id: str, _auth: None = Depends(_portal_auth)):
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
        raise _portal_error("status", project_id, e)


@router.get("/{project_id}/phase/{phase_name}")
async def get_phase_output(project_id: str, phase_name: str, _auth: None = Depends(_portal_auth)):
    # phase_name is joined onto the project directory: ".." would list every
    # project's files, and get_output_dir() would create whatever name is sent.
    if not _SAFE_NAME.match(phase_name):
        raise HTTPException(status_code=404, detail="Phase not found")
    try:
        phase_dir = (await _resolve_run(project_id))["project_dir"] / phase_name
        files = {}
        for f in phase_dir.rglob("*"):
            if f.is_file() and f.suffix in (".md", ".json", ".txt", ".yml", ".yaml"):
                try:
                    files[f.name] = f.read_text()[:5000]
                except Exception as exc:
                    logger.debug("Failed to read phase output file %s: %s", f.name, exc)
        return {"project_id": project_id, "phase": phase_name, "files": files}
    except HTTPException:
        raise
    except Exception as e:
        raise _portal_error("phase", project_id, e)


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
        raise _portal_error("approve", project_id, e)


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
        raise _portal_error("feedback", project_id, e)


# ── Download endpoints ────────────────────────────────────────────────────────

@router.get("/{run_id}/download")
async def portal_download_zip(run_id: str, _auth: None = Depends(_portal_auth)):
    """Download all project artifacts as a ZIP file (portal token or owning-org user)."""
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
async def portal_provenance(run_id: str, _auth: None = Depends(_portal_auth)):
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
