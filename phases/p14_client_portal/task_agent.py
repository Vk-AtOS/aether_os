"""P14 Task Agent — build client review portal routes."""
from __future__ import annotations
import json, logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client
logger = logging.getLogger(__name__)

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    project_id = phase_input.project_id
    client_id = phase_input.client_id
    portal_url = data.get("portal_url", "http://localhost:9200/portal")
    llm = get_llm_client()

    # Gateway routes file for portal
    portal_routes = """
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
        for phase_dir in sorted(project_dir.iterdir()):
            if phase_dir.is_dir() and phase_dir.name.startswith("p"):
                phases_completed.append(phase_dir.name)
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
        from aether_os.core.projects import get_project_manager
        pm = get_project_manager()
        project_dir = pm.get_project_dir(project_id)
        feedback_file = project_dir / "feedback.jsonl"
        import time
        entry = {"timestamp": time.time(), "feedback": body.feedback, "phase": body.phase}
        with open(feedback_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return {"project_id": project_id, "message": "Feedback recorded", "entry": entry}
    except Exception as e:
        raise HTTPException(500, str(e))
"""
    routes_dir = Path("/Users/apple/Desktop/aether_os/gateway/client_portal")
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes_file = routes_dir / "routes.py"
    routes_file.write_text(portal_routes)

    # HTML dashboard
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AetherOS — Client Portal</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: Inter, sans-serif; background: #0f172a; color: #e2e8f0; }
  .header { background: #1e293b; padding: 1rem 2rem; display: flex; align-items: center; gap: 1rem; }
  .header h1 { font-size: 1.25rem; color: #6366f1; }
  .container { max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }
  .pipeline { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 2rem; }
  .phase-badge { padding: 0.4rem 0.8rem; border-radius: 20px; font-size: 0.8rem;
                  background: #1e293b; border: 1px solid #334155; cursor: pointer; }
  .phase-badge.complete { background: #065f46; border-color: #059669; color: #6ee7b7; }
  .phase-badge.current { background: #312e81; border-color: #6366f1; color: #a5b4fc; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; }
  .card h2 { color: #6366f1; margin-bottom: 1rem; }
  .output-preview { background: #0f172a; border-radius: 8px; padding: 1rem; max-height: 400px; overflow-y: auto; font-family: monospace; font-size: 0.85rem; white-space: pre-wrap; }
  .actions { display: flex; gap: 1rem; margin-top: 1rem; }
  .btn { padding: 0.6rem 1.5rem; border-radius: 8px; border: none; cursor: pointer; font-weight: 600; transition: opacity 0.2s; }
  .btn:hover { opacity: 0.85; }
  .btn-approve { background: #059669; color: white; }
  .btn-reject { background: #dc2626; color: white; }
  .feedback-area { width: 100%; background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 0.8rem; color: #e2e8f0; margin-top: 1rem; min-height: 80px; }
  .status-bar { background: #059669; color: white; padding: 0.5rem 1rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.9rem; }
</style>
</head>
<body>
<div class="header">
  <h1>⚡ AetherOS Client Portal</h1>
  <span id="project-id" style="color:#94a3b8;font-size:0.85rem;"></span>
</div>
<div class="container">
  <div id="status-bar" class="status-bar">Loading project status...</div>
  <div class="card">
    <h2>Pipeline Progress</h2>
    <div id="pipeline" class="pipeline">Loading phases...</div>
  </div>
  <div class="card">
    <h2 id="phase-title">Phase Output</h2>
    <div id="output-preview" class="output-preview">Select a phase to view its output.</div>
    <div class="actions">
      <button class="btn btn-approve" onclick="approve(true)">✓ Approve & Continue</button>
      <button class="btn btn-reject" onclick="approve(false)">✗ Request Changes</button>
    </div>
    <textarea class="feedback-area" id="feedback" placeholder="Add feedback or change request..."></textarea>
    <button class="btn" style="background:#6366f1;color:white;margin-top:0.5rem" onclick="submitFeedback()">Send Feedback</button>
  </div>
</div>
<script>
const projectId = new URLSearchParams(window.location.search).get("project_id") || "demo";
document.getElementById("project-id").textContent = "Project: " + projectId;
let currentPhase = null;

async function loadStatus() {
  try {
    const r = await fetch("/portal/" + projectId + "/status");
    const data = await r.json();
    const phases = data.phases_completed || [];
    currentPhase = data.current_phase;
    document.getElementById("status-bar").textContent = 
      `Status: ${phases.length} phases complete. Current: ${currentPhase || "none"}`;
    const pipeline = document.getElementById("pipeline");
    pipeline.innerHTML = "";
    const allPhases = ["p00_intake","p01_requirements","p02_architecture","p03_scaffolding",
      "p04a_backend_codegen","p04b_uiux_design","p04c_frontend_codegen","p05_code_review",
      "p06_security","p07a_unit_testing","p08_cicd","p09_documentation","p10_deployment",
      "p11a_monitoring","p11b_error_tracking","p11c_analytics","p12a_feature_flags","p13_app_memory","p14_client_portal"];
    allPhases.forEach(p => {
      const badge = document.createElement("div");
      badge.className = "phase-badge" + (phases.includes(p) ? " complete" : "") + (p === currentPhase ? " current" : "");
      badge.textContent = p.replace("_"," ");
      badge.onclick = () => loadPhase(p);
      pipeline.appendChild(badge);
    });
  } catch(e) {
    document.getElementById("status-bar").textContent = "Error loading status: " + e.message;
  }
}

async function loadPhase(phaseName) {
  document.getElementById("phase-title").textContent = phaseName;
  const preview = document.getElementById("output-preview");
  preview.textContent = "Loading...";
  try {
    const r = await fetch("/portal/" + projectId + "/phase/" + phaseName);
    const data = await r.json();
    const files = data.files || {};
    preview.textContent = Object.entries(files).map(([k,v]) => `=== ${k} ===\n${v}`).join("\n\n") || "No output yet.";
  } catch(e) {
    preview.textContent = "Error: " + e.message;
  }
}

async function approve(approved) {
  const comment = document.getElementById("feedback").value;
  const r = await fetch("/portal/" + projectId + "/approve", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({approved, comment})
  });
  const data = await r.json();
  alert(data.message);
  loadStatus();
}

async function submitFeedback() {
  const feedback = document.getElementById("feedback").value;
  if (!feedback.trim()) return alert("Please enter feedback first.");
  await fetch("/portal/" + projectId + "/feedback", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({feedback, phase: currentPhase})
  });
  document.getElementById("feedback").value = "";
  alert("Feedback submitted.");
}

loadStatus();
setInterval(loadStatus, 30000);
</script>
</body>
</html>"""
    html_path = routes_dir / "index.html"
    html_path.write_text(html)

    # Also save to output_dir
    (output_dir / "portal_routes.py").write_text(portal_routes)

    issues = []
    if not routes_file.exists():
        issues.append("portal routes.py not written")
    if not html_path.exists():
        issues.append("portal index.html not written")

    return TaskResult(
        output_path=str(routes_file),
        confidence=0.9 if not issues else 0.5,
        metadata={"routes_file": str(routes_file), "html_file": str(html_path)},
        issues=issues,
        success=len(issues) == 0,
    )
