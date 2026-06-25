"""
Dashboard job-management routes: job detail, approve/reject, helpers.

Imports auth_dashboard_router and router from dashboard.py.
Routes are activated when this module is imported by main.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime

from fastapi import HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from src.api.dashboard import auth_dashboard_router, router
from src.api.state import JOB_HISTORY, update_job_approval, add_job_to_history, update_job_pr_url
from src.api.templates import get_base_html
from src.api.websocket_manager import MANAGER
from src.database import SessionLocal
from src.db.job_repo import get_job_stats, get_recent_jobs, get_job_by_id
from src.db.audit_repo import save_audit_log
from src.repo import REPO_MANAGER, PatchApplier, PRCreator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job detail page
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/job/{job_id}", response_class=HTMLResponse)
async def get_job_detail_page(job_id: str, request: Request):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    content = f"""
    <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px">
            <h2 style="margin:0">Job Detail: <span id="job-id-title">{job_id[:8]}</span></h2>
            <div id="status-badges"></div>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:20px; font-size:14px; color:#8b949e">
            <div><strong>Repo:</strong> <span id="job-repo" style="color:#c9d1d9"></span></div>
            <div><strong>Branch:</strong> <span id="job-branch" style="color:#c9d1d9"></span></div>
            <div><strong>Confidence:</strong> <span id="job-confidence" style="color:#c9d1d9"></span></div>
            <div><strong>CI System:</strong> <span id="job-ci" style="color:#c9d1d9"></span></div>
            <div><strong>Language:</strong> <span id="job-lang" style="color:#c9d1d9"></span></div>
            <div><strong>Created:</strong> <span id="job-time" style="color:#c9d1d9"></span></div>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-top:0">Repair Explanation</h3>
        <p id="job-explanation" style="line-height:1.6"></p>
    </div>

    <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px">
            <h3 style="margin:0">Proposed Patch</h3>
            <div id="editor-controls" style="display:flex; gap:10px">
                <button id="btn-toggle-edit" onclick="toggleEditMode()" class="btn">Edit Patch</button>
                <button id="btn-save-edit" onclick="saveEdits()" class="btn btn-primary" style="display:none">Save &amp; Approve</button>
                <button id="btn-cancel-edit" onclick="cancelEdit()" class="btn" style="display:none">Cancel</button>
            </div>
        </div>

        <div id="diff-viewer" style="background:#0d1117; border-radius:6px; padding:15px; font-family:monospace; font-size:13px; overflow-x:auto">
            <!-- Diff will be rendered here -->
        </div>

        <textarea id="patch-editor" style="display:none; width:100%; min-height:400px; background:#0d1117; color:#c9d1d9; border:1px solid #30363d; border-radius:6px; padding:15px; font-family:monospace; font-size:13px; outline:none; resize:vertical"></textarea>
    </div>

    <div id="actions-bar" class="card" style="display:flex; gap:15px">
        <button onclick="approveJob()" class="btn btn-primary" style="flex:1; padding:12px">Approve &amp; Apply</button>
        <button onclick="rejectJob()" class="btn btn-danger" style="flex:1; padding:12px">Reject Patch</button>
    </div>

    <script>
    let currentJob = null;
    let originalPatch = "";

    async function loadJob() {{
        const res = await fetch(`/api/jobs/{job_id}`, {{credentials: 'include'}});
        if (!res.ok) {{
            document.body.innerHTML = '<h1>Job not found</h1>';
            return;
        }}
        currentJob = await res.json();
        originalPatch = currentJob.patch_diff || "";

        document.getElementById('job-repo').textContent = currentJob.repo_name;
        document.getElementById('job-branch').textContent = currentJob.branch;
        document.getElementById('job-confidence').textContent = (currentJob.confidence || 0).toFixed(2);
        document.getElementById('job-ci').textContent = currentJob.ci_system || 'unknown';
        document.getElementById('job-lang').textContent = currentJob.detected_language || 'unknown';
        document.getElementById('job-time').textContent = new Date(currentJob.timestamp).toLocaleString();
        document.getElementById('job-explanation').textContent = currentJob.explanation;

        renderDiff(originalPatch);

        const badges = document.getElementById('status-badges');
        if (currentJob.success) badges.innerHTML += '<span class="status-badge status-success">success</span>';
        if (currentJob.escalated) badges.innerHTML += '<span class="status-badge status-escalated">escalated</span>';
        if (currentJob.approved === true) badges.innerHTML += '<span class="status-badge status-success">approved</span>';
        else if (currentJob.approved === false) badges.innerHTML += '<span class="status-badge status-failed">rejected</span>';

        if (currentJob.approved !== null) {{
            document.getElementById('actions-bar').style.display = 'none';
            document.getElementById('editor-controls').style.display = 'none';
        }}
    }}

    function renderDiff(patch) {{
        const viewer = document.getElementById('diff-viewer');
        if (!patch) {{
            viewer.innerHTML = '<div style="color:#8b949e; font-style:italic">No patch generated for this job.</div>';
            return;
        }}

        const lines = patch.split('\\n');
        let html = '<table style="width:100%; border-collapse:collapse">';
        lines.forEach((line, i) => {{
            let color = '#8b949e'; // context
            let bg = 'transparent';
            if (line.startsWith('+') && !line.startsWith('+++')) {{
                color = '#3fb950'; bg = 'rgba(63, 185, 80, 0.1)';
            }} else if (line.startsWith('-') && !line.startsWith('---')) {{
                color = '#f85149'; bg = 'rgba(248, 81, 73, 0.1)';
            }} else if (line.startsWith('@@')) {{
                color = '#58a6ff'; bg = 'rgba(88, 166, 255, 0.1)';
            }}

            html += `<tr style="background:${{bg}}">
                <td style="width:40px; color:#484f58; text-align:right; padding-right:15px; user-select:none">${{i+1}}</td>
                <td style="color:${{color}}; white-space:pre-wrap">${{escapeHtml(line)}}</td>
            </tr>`;
        }});
        html += '</table>';
        viewer.innerHTML = html;
    }}

    function escapeHtml(text) {{
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }}

    function toggleEditMode() {{
        document.getElementById('diff-viewer').style.display = 'none';
        const editor = document.getElementById('patch-editor');
        editor.style.display = 'block';
        editor.value = originalPatch;

        document.getElementById('btn-toggle-edit').style.display = 'none';
        document.getElementById('btn-save-edit').style.display = 'block';
        document.getElementById('btn-cancel-edit').style.display = 'block';
        document.getElementById('actions-bar').style.display = 'none';
    }}

    function cancelEdit() {{
        document.getElementById('diff-viewer').style.display = 'block';
        document.getElementById('patch-editor').style.display = 'none';
        document.getElementById('btn-toggle-edit').style.display = 'block';
        document.getElementById('btn-save-edit').style.display = 'none';
        document.getElementById('btn-cancel-edit').style.display = 'none';
        document.getElementById('actions-bar').style.display = 'flex';
    }}

    async function saveEdits() {{
        const edited = document.getElementById('patch-editor').value;
        const res = await fetch(`/dashboard/approve/{job_id}`, {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{edited_patch: edited}}),
            credentials: 'include'
        }});
        if (res.ok) location.reload();
        else alert('Failed to save and approve');
    }}

    async function approveJob() {{
        const res = await fetch(`/dashboard/approve/{job_id}`, {{
            method: 'POST',
            credentials: 'include'
        }});
        if (res.ok) location.reload();
    }}

    async function rejectJob() {{
        const res = await fetch(`/dashboard/reject/{job_id}`, {{
            method: 'POST',
            credentials: 'include'
        }});
        if (res.ok) location.reload();
    }}

    loadJob();
    </script>
    """
    return HTMLResponse(content=get_base_html("Job Detail", content, "Dashboard", username))


# ---------------------------------------------------------------------------
# Approve / Reject handlers
# ---------------------------------------------------------------------------

@auth_dashboard_router.post("/dashboard/approve/{job_id}")
async def approve_job(job_id: str, request: Request):
    """Mark a job as approved."""
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    edited_patch = body.get("edited_patch")

    if edited_patch:
        session = SessionLocal()
        try:
            job = get_job_by_id(session, job_id)
            if job:
                job.patch_diff = edited_patch
                job.patch_edited = True
                session.commit()
                for m_job in JOB_HISTORY:
                    if m_job["id"] == job_id:
                        m_job["patch_diff"] = edited_patch
                        break
        finally:
            session.close()

    if update_job_approval(job_id, True):
        job_data = _find_job_by_id(job_id)
        if job_data:
            def _broadcast(jd: dict) -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(
                        MANAGER.broadcast_job_update("job_approved", jd))
                finally:
                    loop.close()

            threading.Thread(target=_broadcast, args=(job_data,), daemon=True).start()

        token = request.cookies.get("session_token")
        from src.api.auth import verify_session_token
        username = verify_session_token(token) or "admin"

        session = SessionLocal()
        save_audit_log(session, "approve_job", username, job_id, details=f"Patch edited: {bool(edited_patch)}")
        session.close()

        threading.Thread(target=_apply_patch_and_create_pr, args=(job_id,), daemon=True).start()
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Job not found")


@auth_dashboard_router.post("/dashboard/reject/{job_id}")
async def reject_job(job_id: str, request: Request):
    """Mark a job as rejected."""
    if update_job_approval(job_id, False):
        job_data = _find_job_by_id(job_id)
        if job_data:
            def _broadcast(jd: dict) -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(
                        MANAGER.broadcast_job_update("job_rejected", jd))
                finally:
                    loop.close()

            threading.Thread(target=_broadcast, args=(job_data,), daemon=True).start()

        token = request.cookies.get("session_token")
        from src.api.auth import verify_session_token
        username = verify_session_token(token) or "admin"

        session = SessionLocal()
        save_audit_log(session, "reject_job", username, job_id)
        session.close()

        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Job not found")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _find_job_by_id(job_id: str) -> dict | None:
    """Find a job in memory or DB; returns a plain dict or None."""
    for job in JOB_HISTORY:
        if job["id"] == job_id:
            return job

    session = SessionLocal()
    try:
        job = get_job_by_id(session, job_id)
        if job:
            return {
                "id": job.id,
                "repo_name": job.repo_name,
                "branch": job.branch,
                "patch_diff": job.patch_diff,
                "ci_system": job.ci_system,
                "timestamp": job.timestamp.isoformat() if hasattr(job.timestamp, "isoformat") else str(job.timestamp),
                "success": job.success,
                "confidence": job.confidence,
                "escalated": job.escalated,
                "explanation": job.explanation,
                "approved": job.approved
            }
    finally:
        session.close()
    return None


def _apply_patch_and_create_pr(job_id: str) -> None:
    """Background task: apply an approved patch and open a PR."""
    try:
        job = _find_job_by_id(job_id)
        if not job or not job.get("patch_diff"):
            return

        repo_name = job["repo_name"]
        patch_diff = job["patch_diff"]
        ci_system = job.get("ci_system")

        repo_folder = repo_name.split("/")[-1]
        local_path = REPO_MANAGER.get_local_path(repo_folder)

        if not local_path:
            logger.warning("Repository %s not found in local cache.", repo_name)
            return

        applier = PatchApplier(local_path)
        branch_name = f"dcsp/fix-{job_id[:8]}"

        try:
            applier.create_branch(branch_name)
            result = applier.apply(patch_diff)

            if result.success:
                applier.commit_patch(f"fix: DCSP auto-repair for {repo_name}")
                applier.push_branch(branch_name)

                creator = PRCreator(repo_name)
                title = f"DCSP Auto-fix: {repo_name}"
                body = f"Automated repair generated by DCSP.\n\n```diff\n{patch_diff[:500]}...\n```"

                if ci_system == "gitlab_ci":
                    pr_res = creator.create_gitlab_mr(branch_name, title, body)
                else:
                    pr_res = creator.create_github_pr(branch_name, title, body)

                if pr_res.success:
                    update_job_pr_url(job_id, pr_res.url)
                    logger.info("Created PR for job %s: %s", job_id, pr_res.url)
                else:
                    logger.warning("Failed to create PR for job %s: %s", job_id, pr_res.error)
            else:
                logger.warning("Failed to apply patch for job %s: %s", job_id, result.error)
        except Exception as e:
            logger.exception("Exception during patch application for job %s", job_id)
    except Exception as e:
        logger.exception("Background patch application failed for job %s", job_id)
