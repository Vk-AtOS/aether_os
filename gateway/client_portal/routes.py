from __future__ import annotations
import io
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from aether_os.core.identity import portal_access
from aether_os.core.projects import get_project_manager
from aether_os.core.run_app import safe_fs
from aether_os.gateway.client_portal.provenance import _build_provenance
from aether_os.gateway.dependencies import assert_run_in_org, get_current_user, security_scheme

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/portal", tags=["client-portal"])


class FeedbackBody(BaseModel):
    # Bounded: a portal token is held by an external client and every call appends to feedback.jsonl on disk
    # (KAN-69 R6: the body was unbounded, so one token could fill the disk).
    feedback: str = Field(max_length=5000)
    phase: Optional[str] = Field(default=None, max_length=128)


class ApproveBody(BaseModel):
    approved: bool
    comment: Optional[str] = Field(default=None, max_length=2000)


# A run / project id as a single safe path component: these ids are joined onto the
# projects directory, so "..", separators and empty values must never get that far.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


async def _portal_auth(
    request: Request,
    portal_token: Optional[str] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> Dict[str, Any]:
    """Auth for every /portal/{id}/... route; returns who is calling. Accepts either:
      - a portal token issued for this project (POST /factory/runs/{id}/portal-tokens):
        X-Portal-Token header, or ?portal_token= (query form kept for plain
        download links; it does end up in access logs)
      - a signed-in user (or API key) of the organisation that owns the run.
    A valid session from another organisation is not enough: 404, same as any
    other run route, so run ids cannot be probed. A token is checked before the
    project is looked up, so a bad token learns nothing about which ids exist.
    """
    project_id = request.path_params.get("project_id") or request.path_params.get("run_id") or ""
    if not _SAFE_NAME.match(project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    supplied = request.headers.get("x-portal-token") or portal_token
    if supplied:
        route = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        principal = await portal_access.verify_token(project_id, supplied, request.method, route)
        if principal is None:
            raise HTTPException(status_code=401, detail="Portal authentication required")
        return principal

    if credentials is None:
        raise HTTPException(status_code=401, detail="Portal authentication required")
    user = await get_current_user(request, credentials)
    await assert_run_in_org(project_id, user)
    return {"kind": "user", "id": user.get("user_id") or user.get("sub") or "-",
            "label": user.get("email") or user.get("sub") or "", "org_id": user["org_id"]}


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
async def get_project_status(project_id: str, _auth: Dict[str, Any] = Depends(_portal_auth)):
    try:
        rec = await _resolve_run(project_id)
        project_dir = rec["project_dir"]
        phases_completed = []
        # safe_fs throughout: the sandboxed app writes in project_dir, so a planted link is
        # never listed, entered or read.
        phases_completed = [n for n, is_dir in safe_fs.list_dir(project_dir)
                            if is_dir and n.startswith("p")]

        # Extract requirements text from p01 intake output
        requirement_text = ""
        specification_text = ""
        try:
            p01_dir = Path("p01_intake_requirements")   # relative to project_dir
            # Try all known artifact locations written by p01
            intake_candidates = [
                p01_dir / "intake" / "intake.json",
                p01_dir / "requirements.json",
            ]
            for intake_json in intake_candidates:
                intake_text = safe_fs.read_text_or_none(project_dir, intake_json)
                if intake_text is not None:
                    intake_data = json.loads(intake_text)
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
                    md_text = safe_fs.read_text_or_none(project_dir, req_md)
                    if md_text is not None:
                        requirement_text = md_text[:3000]
                        break

            specification_text = requirement_text
        except Exception as _re:
            logger.debug("Could not load intake data: %s", _re)

        # Best-effort compliance score from delivery JSON
        compliance_score = None
        try:
            delivery_text = safe_fs.read_text_or_none(project_dir, "p12_delivery/delivery.json")
            if delivery_text is not None:
                delivery_data = json.loads(delivery_text)
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
        raise _portal_error("status", project_id, e) from e


@router.get("/{project_id}/phase/{phase_name}")
async def get_phase_output(project_id: str, phase_name: str, _auth: Dict[str, Any] = Depends(_portal_auth)):
    # phase_name is joined onto the project directory: ".." would list every
    # project's files, and get_output_dir() would create whatever name is sent.
    if not _SAFE_NAME.match(phase_name):
        raise HTTPException(status_code=404, detail="Phase not found")
    try:
        project_dir = (await _resolve_run(project_id))["project_dir"]
        files = {}
        for f in safe_fs.walk_files(project_dir, phase_name):
            if f.suffix in (".md", ".json", ".txt", ".yml", ".yaml"):
                text = safe_fs.read_text_or_none(project_dir, f, max_bytes=1024 * 1024)
                if text is not None:
                    files[f.name] = text[:5000]
        return {"project_id": project_id, "phase": phase_name, "files": files}
    except HTTPException:
        raise
    except Exception as e:
        raise _portal_error("phase", project_id, e) from e


@router.post("/{project_id}/approve")
async def approve_phase(
    project_id: str,
    body: ApproveBody,
    principal: Dict[str, Any] = Depends(_portal_auth),
):
    """Record the client's sign-off (or change request) for this project.

    Stored in portal_approvals and ledgered. An approval while the build is
    waiting at spec review releases that gate; otherwise it is a record only —
    nothing is re-run on a change request.
    """
    await _resolve_run(project_id)  # 404 for an unknown project, after authentication
    try:
        approval, created = await portal_access.record_approval(project_id, principal, body.approved, body.comment)
    except Exception as e:
        raise _portal_error("approve", project_id, e) from e
    if approval["applied_to"] == "spec_review":
        message = "Approval recorded. The build continues past spec review."
    else:
        message = "Approval recorded." if body.approved else "Change request recorded."
    return {"project_id": project_id, "approved": approval["approved"], "approval_id": approval["id"],
            "recorded_at": approval["created_at"], "recorded_by": approval["actor_label"],
            "applied_to": approval["applied_to"], "duplicate": not created, "message": message}


@router.post("/{project_id}/feedback")
async def submit_feedback(
    project_id: str,
    body: FeedbackBody,
    _auth: Dict[str, Any] = Depends(_portal_auth),
):
    try:
        import time
        rec = await _resolve_run(project_id)
        project_dir = rec["project_dir"]
        project_dir.mkdir(parents=True, exist_ok=True)
        entry = {"timestamp": time.time(), "feedback": body.feedback, "phase": body.phase}
        safe_fs.safe_append_text(project_dir, project_dir / "feedback.jsonl", json.dumps(entry) + "\n")
        return {"project_id": project_id, "message": "Feedback recorded", "entry": entry}
    except HTTPException:
        raise
    except Exception as e:
        raise _portal_error("feedback", project_id, e) from e


# ── Download endpoints ────────────────────────────────────────────────────────

@router.get("/{run_id}/download")
async def portal_download_zip(run_id: str, _auth: Dict[str, Any] = Depends(_portal_auth)):
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
            for rel_path in safe_fs.walk_files(project_dir, skip_dirs=_SKIP_DIRS):
                file_path = project_dir / rel_path
                if file_path.name == "run_preview.py":
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
                # Links, special files and anything over 5 MB (counted while reading) are left out
                data = safe_fs.read_bytes_or_none(project_dir, rel_path, max_bytes=5 * 1024 * 1024)
                if data is None:
                    logger.debug("Skipping %s in ZIP", file_path)
                    continue
                zf.writestr(str(rel_path), data)

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
        raise HTTPException(status_code=500, detail="Failed to build ZIP archive") from exc

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
async def portal_provenance(run_id: str, _auth: Dict[str, Any] = Depends(_portal_auth)):
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
