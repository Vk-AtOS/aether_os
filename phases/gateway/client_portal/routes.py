
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from aether_os.core.run_app import safe_fs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/portal", tags=["client-portal"])


class FeedbackBody(BaseModel):
    feedback: str
    phase: Optional[str] = None


class ApproveBody(BaseModel):
    approved: bool
    comment: Optional[str] = None


@router.get("/{project_id}/status")
async def get_project_status(project_id: str):
    try:
        from aether_os.core.projects import get_project_manager
        pm = get_project_manager()
        project = pm.get_project(project_id)
        if not project:
            raise HTTPException(404, f"Project {project_id} not found")
        project_dir = pm.get_project_dir(project_id)
        phases_completed = []
        phases_completed = [n for n, is_dir in safe_fs.list_dir(project_dir)   # links left out
                            if is_dir and n.startswith("p")]
        return {
            "project_id": project_id,
            "project_name": project.name,
            "client_id": project.client_id,
            "phases_completed": phases_completed,
            "current_phase": phases_completed[-1] if phases_completed else None,
            "metadata": project.metadata,
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
        project_dir = pm.get_project_dir(project_id)
        files = {}
        for f in safe_fs.walk_files(project_dir, phase_dir):
            if f.suffix in (".md", ".json", ".txt", ".yml", ".yaml"):
                text = safe_fs.read_text_or_none(project_dir, f, max_bytes=1024 * 1024)
                if text is not None:
                    files[f.name] = text[:5000]
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
        from aether_os.core.projects import get_project_manager
        pm = get_project_manager()
        project_dir = pm.get_project_dir(project_id)
        feedback_file = project_dir / "feedback.jsonl"
        import time
        entry = {"timestamp": time.time(), "feedback": body.feedback, "phase": body.phase}
        safe_fs.safe_append_text(project_dir, feedback_file, json.dumps(entry) + "\n")
        return {"project_id": project_id, "message": "Feedback recorded", "entry": entry}
    except Exception as e:
        raise HTTPException(500, str(e))
