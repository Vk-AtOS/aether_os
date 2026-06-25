"""
Dashboard view routes: incidents, github, security.

Routes that were extracted from this file:
  - dashboard_analytics.py  — analytics + intelligence
  - dashboard_compliance.py — compliance + audit
  - dashboard_admin.py      — admin tenant management + API keys

Imports auth_dashboard_router from dashboard.py and registers routes on it.
Routes in this module are activated when this module is imported by main.py.
"""

from __future__ import annotations

import logging
import os

from fastapi import Request
from fastapi.responses import HTMLResponse

from src.api.dashboard import auth_dashboard_router
from src.api.templates import get_base_html

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/incidents", response_class=HTMLResponse)
async def get_incidents_page(request: Request):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    content = """
    <div class="metrics-row">
        <div class="metric-card">
            <div class="metric-label">Active Incidents</div>
            <div id="inc-active" class="metric-value">Loading...</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Escalated</div>
            <div id="inc-escalated" class="metric-value" style="color: var(--error-color)">Loading...</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Resolved</div>
            <div id="inc-resolved" class="metric-value" style="color: var(--success-color)">Loading...</div>
        </div>
    </div>

    <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px">
            <h3 style="margin:0">Recent Incidents</h3>
            <div style="display:flex; gap:10px; align-items:center">
                <label style="font-size:14px; color:#8b949e">Filter:</label>
                <select id="filter-status" onchange="loadIncidents()"
                    style="padding:6px 10px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9">
                    <option value="">All</option>
                    <option value="active">Active</option>
                    <option value="escalated">Escalated</option>
                    <option value="resolved">Resolved</option>
                </select>
            </div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>First Seen</th>
                    <th>Error Type</th>
                    <th>Language</th>
                    <th>Repos Affected</th>
                    <th>Job Count</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody id="incidents-tbody"></tbody>
        </table>
    </div>

    <script>
    async function loadStats() {
        const res = await fetch('/api/incidents/stats', {credentials: 'include'});
        const stats = await res.json();
        document.getElementById('inc-active').innerText = stats.active;
        document.getElementById('inc-escalated').innerText = stats.escalated;
        document.getElementById('inc-resolved').innerText = stats.resolved;
    }

    async function loadIncidents() {
        const status = document.getElementById('filter-status').value;
        let url = '/api/incidents?limit=100';
        if (status) url += '&status=' + status;

        const res = await fetch(url, {credentials: 'include'});
        const data = await res.json();
        const tbody = document.getElementById('incidents-tbody');
        tbody.innerHTML = '';

        data.incidents.forEach(i => {
            const row = document.createElement('tr');

            let badgeStyle = 'background-color: rgba(139, 148, 158, 0.2); color: #8b949e; border: 1px solid rgba(139, 148, 158, 0.4);'; // resolved (grey)
            if (i.status === 'active') {
                badgeStyle = 'background-color: rgba(88, 166, 255, 0.2); color: #58a6ff; border: 1px solid rgba(88, 166, 255, 0.4);'; // active (blue)
            } else if (i.status === 'escalated') {
                badgeStyle = 'background-color: rgba(218, 54, 51, 0.2); color: #f85149; border: 1px solid rgba(218, 54, 51, 0.4);'; // escalated (red)
            }

            const repos = (i.affected_repos || []).join(', ');

            let actions = '';
            if (i.status !== 'resolved') {
                actions = `
                    <button class="action-btn" style="color:#238636; border-color:#238636" onclick="resolveIncident('${i.id}')">Resolve</button>
                    <button class="action-btn" style="color:#d29922; border-color:#d29922" onclick="escalateIncident('${i.id}')">Escalate</button>
                `;
            }

            row.innerHTML = `
                <td style="font-size:12px; color:#8b949e">${i.first_seen.substring(0,16)}</td>
                <td style="font-weight:bold">${i.error_type || 'Unknown'}</td>
                <td><span class="badge badge-info">${i.language || 'unknown'}</span></td>
                <td style="max-width:200px; overflow:hidden; text-overflow:ellipsis" title="${repos}">${repos}</td>
                <td>${i.job_count}</td>
                <td><span class="status-badge" style="${badgeStyle}">${i.status}</span></td>
                <td>${actions}</td>
            `;
            tbody.appendChild(row);
        });
    }

    async function resolveIncident(id) {
        const res = await fetch(`/api/incidents/${id}/resolve`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({resolution: 'Manually resolved'}),
            credentials: 'include'
        });
        if (res.ok) location.reload();
    }

    async function escalateIncident(id) {
        const res = await fetch(`/api/incidents/${id}/escalate`, {
            method: 'POST',
            credentials: 'include'
        });
        if (res.ok) location.reload();
    }

    loadStats();
    loadIncidents();
    </script>
    """
    return HTMLResponse(content=get_base_html("Incidents", content, "Incidents", username))


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/github", response_class=HTMLResponse)
async def get_github_page(request: Request):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    github_app_slug = os.environ.get("GITHUB_APP_SLUG", "dcsp-autofix")
    install_url = (
        "https://github.com/apps/" + github_app_slug + "/installations/new"
    )
    _connect_block = (
        '<div class="card" style="border-left: 3px solid #58a6ff;">'
        "<h3 style=\"margin-top:0\">GitHub App Integration</h3>"
        "<p style=\"color:#8b949e; margin-bottom:16px\">"
        "Connect DCSP to your GitHub repositories for autonomous fix PRs. "
        "Once installed, DCSP will automatically create fix PRs when it detects "
        "issues in your repositories."
        "</p>"
        '<a href="' + install_url + '" '
        'class="btn btn-primary" target="_blank" '
        'style="display:inline-block; text-decoration:none;">'
        "Install GitHub App"
        "</a>"
        "<p style=\"font-size:12px; color:#8b949e; margin-top:10px\">"
        "After installing, return here to verify the connection status below."
        "</p>"
        "</div>"
    )

    content = """
    <div class="card">
        <h2 style="margin-top:0">GitHub Integration</h2>
        <p style="color:#8b949e">Connect DCSP to your GitHub repositories to enable automated CI failure repairs.</p>
    </div>

    """ + _connect_block + """

    <div id="setup-card" class="card">
        <h3 style="margin-top:0">Connection Status</h3>
        <div id="status-content">
            <p>Checking configuration...</p>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-top:0">Active Installations</h3>
        <table>
            <thead>
                <tr>
                    <th>Account</th>
                    <th>Type</th>
                    <th>Repositories</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody id="installations-tbody">
                <tr><td colspan="4" style="text-align:center; color:#8b949e">Loading...</td></tr>
            </tbody>
        </table>
    </div>

    <script>
    async function checkStatus() {
        const res = await fetch('/github/status', {credentials: 'include'});
        const data = await res.json();
        const el = document.getElementById('status-content');

        if (data.configured) {
            el.innerHTML = `
                <div style="display:flex; align-items:center; gap:15px; margin-bottom:15px">
                    <span style="color:#238636; font-size:20px">&#10003;</span>
                    <div>
                        <strong>GitHub App Configured</strong><br>
                        <span style="font-size:13px; color:#8b949e">App ID: ${data.app_id}</span>
                    </div>
                </div>
                <button onclick="startOAuth()" class="btn btn-primary">Connect New Account</button>
            `;
        } else {
            el.innerHTML = `
                <div style="display:flex; align-items:center; gap:15px; margin-bottom:15px">
                    <span style="color:#da3633; font-size:20px">&#9888;</span>
                    <div>
                        <strong>GitHub App Not Configured</strong><br>
                        <span style="font-size:13px; color:#8b949e">Missing GITHUB_APP_ID or CLIENT_ID env vars.</span>
                    </div>
                </div>
                <p style="font-size:13px">Check your .env file to enable GitHub integration.</p>
            `;
        }
    }

    async function loadInstallations() {
        const res = await fetch('/github/installations', {credentials: 'include'});
        const data = await res.json();
        const tbody = document.getElementById('installations-tbody');
        tbody.innerHTML = '';

        if (data.installations.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:#8b949e">No installations found</td></tr>';
            return;
        }

        data.installations.forEach(i => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td><strong>${i.account_login}</strong></td>
                <td><span class="badge badge-info">${i.account_type}</span></td>
                <td>${i.repos.length} repos</td>
                <td><span style="color:#238636">Active</span></td>
            `;
            tbody.appendChild(row);
        });
    }

    async function startOAuth() {
        const res = await fetch('/github/oauth/start', {credentials: 'include'});
        const data = await res.json();
        if (data.url) {
            window.location.href = data.url;
        } else {
            alert('Error: ' + (data.error || 'Failed to start OAuth'));
        }
    }

    checkStatus();
    loadInstallations();
    </script>
    """

    return HTMLResponse(content=get_base_html("GitHub", content, "GitHub", username))


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/security", response_class=HTMLResponse)
async def get_security_page(request: Request):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    content = """
    <div class="card" style="display:flex; justify-content:space-between; align-items:center">
        <div>
            <h2 style="margin-top:0">Security Audit</h2>
            <p style="color:#8b949e">System configuration and safety check.</p>
        </div>
        <div style="text-align:center">
            <div id="security-score" style="font-size:48px; font-weight:bold; line-height:1">--</div>
            <div style="font-size:12px; color:#8b949e; margin-top:5px">Security Score</div>
        </div>
    </div>

    <div class="metrics-row">
        <div class="metric-card">
            <div class="metric-label">Passed Checks</div>
            <div id="sec-passed" class="metric-value">--</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Failed Checks</div>
            <div id="sec-failed" class="metric-value">--</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Critical Findings</div>
            <div id="sec-critical" class="metric-value">--</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">High Findings</div>
            <div id="sec-high" class="metric-value">--</div>
        </div>
    </div>

    <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px">
            <h3 style="margin:0">Findings</h3>
            <button onclick="runAudit()" class="btn btn-primary">Run Audit</button>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Severity</th>
                    <th>Category</th>
                    <th>Title</th>
                    <th>Status</th>
                    <th>Remediation</th>
                </tr>
            </thead>
            <tbody id="audit-tbody">
                <tr><td colspan="5" style="text-align:center; color:#8b949e">Loading audit results...</td></tr>
            </tbody>
        </table>
    </div>

    <script>
    async function runAudit() {
        const res = await fetch('/api/security/audit', {credentials: 'include'});
        const data = await res.json();

        const scoreEl = document.getElementById('security-score');
        scoreEl.innerText = data.score;
        if (data.score >= 80) scoreEl.style.color = '#3fb950';
        else if (data.score >= 50) scoreEl.style.color = '#e3b341';
        else scoreEl.style.color = '#f85149';

        document.getElementById('sec-passed').innerText = data.passed;
        document.getElementById('sec-failed').innerText = data.failed;
        document.getElementById('sec-critical').innerText = data.critical;
        document.getElementById('sec-high').innerText = data.high;

        const tbody = document.getElementById('audit-tbody');
        tbody.innerHTML = '';

        data.findings.forEach(f => {
            const row = document.createElement('tr');

            const severityColors = {
                'critical': '#f85149',
                'high': '#d29922',
                'medium': '#e3b341',
                'low': '#3fb950',
                'info': '#8b949e'
            };
            const sevColor = severityColors[f.severity] || '#8b949e';

            const statusText = f.passed ? 'PASSED' : 'FAILED';
            const statusColor = f.passed ? '#3fb950' : '#f85149';

            row.innerHTML = `
                <td><span class="status-badge" style="color:${sevColor}; border-color:${sevColor}">${f.severity}</span></td>
                <td style="color:#8b949e">${f.category}</td>
                <td style="font-weight:bold">${f.title}</td>
                <td style="color:${statusColor}; font-weight:bold">${statusText}</td>
                <td style="font-size:12px; max-width:300px">${f.remediation || 'No action needed.'}</td>
            `;
            tbody.appendChild(row);
        });
    }

    runAudit();
    </script>
    """
    return HTMLResponse(content=get_base_html("Security", content, "Security", username))
