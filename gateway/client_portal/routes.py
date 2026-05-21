
from __future__ import annotations
import datetime
import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/portal", tags=["client-portal"])


class FeedbackBody(BaseModel):
    feedback: str
    phase: Optional[str] = None


class ApproveBody(BaseModel):
    approved: bool
    comment: Optional[str] = None


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
            intake_json = project_dir / "p01_intake_requirements" / "intake" / "intake.json"
            if intake_json.exists():
                intake_data = json.loads(intake_json.read_text())
                requirement_text = (
                    intake_data.get("raw_text") or
                    intake_data.get("structured_requirements") or ""
                )
            # Use raw_text as spec; only fall back to requirements.md if raw_text is short
            if len(requirement_text) > 100:
                specification_text = requirement_text
            else:
                req_md = project_dir / "p01_intake_requirements" / "requirements" / "requirements.md"
                if req_md.exists():
                    specification_text = req_md.read_text()[:3000]
                else:
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
        except Exception:
            pass

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
                except Exception:
                    pass
        return {"project_id": project_id, "phase": phase_name, "files": files}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/{project_id}/approve")
async def approve_phase(project_id: str, body: ApproveBody):
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
async def submit_feedback(project_id: str, body: FeedbackBody):
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


# ── Provenance helper ─────────────────────────────────────────────────────────

def _build_provenance(run_detail: dict, run_id: str) -> str:
    """Build a Markdown provenance document for the build."""
    phases = run_detail.get("phases", {}) or {}
    phase_lines: list[str] = []
    for phase_name, phase_data in phases.items():
        if isinstance(phase_data, dict):
            status_icon = "✅" if phase_data.get("status") == "completed" else "⚠️"
            duration = phase_data.get("duration_seconds", "?")
            phase_lines.append(f"| {status_icon} | {phase_name} | {duration}s |")

    phases_table = (
        "\n".join(phase_lines)
        if phase_lines
        else "| - | (phase data not recorded) | - |"
    )

    requirements_text = (
        run_detail.get("requirements", run_detail.get("raw_input", "See requirements.txt")) or ""
    )
    if isinstance(requirements_text, list):
        requirements_text = "\n".join(requirements_text)
    requirements_text = str(requirements_text)[:2000]

    built_at = str(run_detail.get("created_at", datetime.datetime.utcnow().isoformat()))[:19]
    compliance_score = run_detail.get("compliance_score", "See compliance_report.pdf")

    return f"""# Build Provenance Document

**Project:** {run_detail.get("project_name", "Unknown")}
**Run ID:** `{run_id}`
**Built:** {built_at} UTC
**Domain:** {run_detail.get("domain", "general")}
**Pipeline Version:** AetherOS 20-phase factory

## Build Phases

| Status | Phase | Duration |
|--------|-------|----------|
{phases_table}

## Architecture Decisions

{run_detail.get("architecture_summary", "See architecture.json in this archive.")}

## Requirements

```
{requirements_text}
```

## Deployment

```bash
# Quick start
docker-compose up --build

# Or without Docker:
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## Compliance

Compliance score: {compliance_score}
Full report: `compliance_report.pdf` (if generated)

---
*Generated by AetherOS Factory — {datetime.datetime.utcnow().strftime("%Y-%m-%d")}*
"""


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
        _SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv", ".mypy_cache"}
        _SKIP_SUFFIXES = {".pyc", ".pyo", ".db", ".db-shm", ".db-wal", ".log"}
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for file_path in project_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                # Skip hidden dirs/files (e.g. .git, .env) and heavy/noisy dirs
                parts_set = set(file_path.parts)
                if any(part.startswith(".") for part in file_path.parts):
                    continue
                if parts_set & _SKIP_DIRS:
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
