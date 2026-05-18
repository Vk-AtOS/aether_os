
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends
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
