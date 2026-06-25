"""
Dashboard compliance and audit routes.

Routes registered on auth_dashboard_router (imported from dashboard.py).
This module is imported by main.py so the routes self-register.
"""

from __future__ import annotations

import io
import csv
import logging
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from fastapi import Request
from fastapi.responses import HTMLResponse, StreamingResponse

from src.api.dashboard import auth_dashboard_router
from src.api.templates import get_base_html
from src.database import SessionLocal
from src.db.audit_repo import save_audit_log, get_audit_logs
from src.models import RepairJob

logger = logging.getLogger(__name__)


def _get_tenant_id(request: "Request") -> str | None:
    """Extract the tenant_id from the current session cookie."""
    from src.api.auth import get_session_tenant_id
    token = request.cookies.get("session_token")
    return get_session_tenant_id(token)


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/compliance", response_class=HTMLResponse)
async def get_compliance_page(request: Request):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    content = """
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
        <h2>Compliance Report</h2>
        <div style="display: flex; gap: 10px;">
            <a href="/api/compliance/export?format=csv" target="_blank" class="btn">Export CSV</a>
            <a href="/api/compliance/export?format=pdf" target="_blank" class="btn">Export PDF</a>
        </div>
    </div>

    <div class="card">
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Job ID</th>
                        <th>Timestamp</th>
                        <th>Repository</th>
                        <th>Status</th>
                        <th>Confidence</th>
                        <th>Approval</th>
                        <th>Patch Size</th>
                    </tr>
                </thead>
                <tbody id="compliance-table"></tbody>
            </table>
        </div>
    </div>

    <script>
        async function loadCompliance() {
            const res = await fetch('/api/metrics'); // Reuse metrics endpoint for recent jobs
            const data = await res.json();

            const table = document.getElementById('compliance-table');
            data.recent_jobs.forEach(job => {
                let approval = 'Pending';
                if (job.approved === true) approval = 'Approved (Admin)';
                else if (job.approved === false) approval = 'Rejected (Admin)';

                const patchSize = job.patch_diff ? job.patch_diff.split('\\n').length : 0;

                table.innerHTML += `
                    <tr>
                        <td style="font-family: monospace; font-size: 12px;">${job.id.substring(0,8)}</td>
                        <td>${new Date(job.timestamp).toLocaleString()}</td>
                        <td>${job.repo_name}</td>
                        <td>${job.success ? 'Success' : 'Failed'}</td>
                        <td>${job.confidence.toFixed(2)}</td>
                        <td>${approval}</td>
                        <td>${patchSize} lines</td>
                    </tr>
                `;
            });
        }
        loadCompliance();
    </script>
    """
    return HTMLResponse(content=get_base_html("Compliance", content, "Compliance", username))


@auth_dashboard_router.get("/api/compliance/export")
async def export_compliance(request: Request, format: str = "csv"):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "admin"
    tenant_id = _get_tenant_id(request)

    session = SessionLocal()
    try:
        save_audit_log(session, "export_compliance", username, details=f"Format: {format}", ip_address=request.client.host)

        q = session.query(RepairJob).order_by(RepairJob.timestamp.desc())
        if tenant_id:
            q = q.filter(RepairJob.tenant_id == tenant_id)
        jobs = q.all()

        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Job ID", "Timestamp", "Repo", "Branch", "Status", "Confidence", "Approved", "Patch Lines"])
            for j in jobs:
                writer.writerow([
                    j.id, j.timestamp, j.repo_name, j.branch,
                    "Success" if j.success else "Failed", j.confidence,
                    "Yes" if j.approved else ("No" if j.approved is False else "Pending"),
                    len(j.patch_diff.split('\n')) if j.patch_diff else 0
                ])
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=compliance_report.csv"}
            )

        elif format == "pdf":
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            elements = []

            elements.append(Paragraph("DCSP Compliance Report", styles['Title']))
            elements.append(Spacer(1, 12))
            elements.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}", styles['Normal']))
            elements.append(Spacer(1, 24))

            data = [["Job ID", "Timestamp", "Repo", "Status", "Approved"]]
            for j in jobs[:50]:  # Limit to 50 for PDF demo
                data.append([
                    j.id[:8], j.timestamp.strftime("%Y-%m-%d %H:%M"),
                    j.repo_name, "Success" if j.success else "Fail",
                    "Yes" if j.approved else "No"
                ])

            t = Table(data)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            elements.append(t)

            doc.build(elements)
            buffer.seek(0)
            return StreamingResponse(
                buffer,
                media_type="application/pdf",
                headers={"Content-Disposition": "attachment; filename=compliance_report.pdf"}
            )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/audit", response_class=HTMLResponse)
async def get_audit_page(request: Request):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    session = SessionLocal()
    logs = get_audit_logs(session, limit=50)
    session.close()

    rows = ""
    for log in logs:
        rows += f"""
        <tr>
            <td>{log.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</td>
            <td>{log.action}</td>
            <td>{log.actor}</td>
            <td>{log.job_id or '-'}</td>
            <td>{log.details or '-'}</td>
            <td>{log.ip_address or '-'}</td>
        </tr>
        """

    content = f"""
    <h2>Audit Log</h2>
    <div class="card">
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>Action</th>
                        <th>Actor</th>
                        <th>Job ID</th>
                        <th>Details</th>
                        <th>IP Address</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    """
    return HTMLResponse(content=get_base_html("Audit Log", content, "Audit Log", username))
