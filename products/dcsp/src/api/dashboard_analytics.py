"""
Dashboard analytics and intelligence routes.

Routes registered on auth_dashboard_router (imported from dashboard.py).
This module is imported by main.py so the routes self-register.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import Request
from fastapi.responses import HTMLResponse

from src.api.dashboard import auth_dashboard_router
from src.api.templates import get_base_html
from src.database import SessionLocal
from src.models import RepairJob

logger = logging.getLogger(__name__)


def _get_tenant_id(request: "Request") -> str | None:
    """Extract the tenant_id from the current session cookie."""
    from src.api.auth import get_session_tenant_id
    token = request.cookies.get("session_token")
    return get_session_tenant_id(token)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/analytics", response_class=HTMLResponse)
async def get_analytics_page(request: Request):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    content = """
    <div class="metrics-row">
        <div class="metric-card">
            <div class="metric-label">Total Repairs (30d)</div>
            <div id="an-total" class="metric-value">Loading...</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Auto-Repaired</div>
            <div id="an-auto" class="metric-value">Loading...</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Est. Hours Saved</div>
            <div id="an-hours" class="metric-value">Loading...</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Est. Cost Saved</div>
            <div id="an-cost" class="metric-value" style="color: var(--success-color)">Loading...</div>
        </div>
    </div>

    <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 30px;">
        <div class="card">
            <h3 style="margin-top: 0;">Repairs per Day (Last 30 Days)</h3>
            <canvas id="repairsChart"></canvas>
        </div>
        <div class="card">
            <h3 style="margin-top: 0;">Confidence Distribution</h3>
            <canvas id="confidenceChart"></canvas>
        </div>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
        <div class="card">
            <h3 style="margin-top: 0;">Per-Repo Breakdown</h3>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Repo</th>
                            <th>Repairs</th>
                            <th>Success %</th>
                            <th>Avg Conf.</th>
                        </tr>
                    </thead>
                    <tbody id="repo-table"></tbody>
                </table>
            </div>
        </div>
        <div class="card">
            <h3 style="margin-top: 0;">Top Error Types</h3>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Error Fingerprint</th>
                            <th>Count</th>
                            <th>Success %</th>
                        </tr>
                    </thead>
                    <tbody id="error-table"></tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        async function loadAnalytics() {
            const res = await fetch('/api/analytics');
            const data = await res.json();

            document.getElementById('an-total').innerText = data.total_jobs;
            document.getElementById('an-auto').innerText = `${data.success_count} (${(data.success_rate * 100).toFixed(1)}%)`;
            document.getElementById('an-hours').innerText = data.hours_saved;
            document.getElementById('an-cost').innerText = `$${data.cost_saved.toLocaleString()}`;

            // Charts
            const ctx1 = document.getElementById('repairsChart').getContext('2d');
            new Chart(ctx1, {
                type: 'bar',
                data: {
                    labels: Object.keys(data.jobs_per_day),
                    datasets: [{
                        label: 'Repairs',
                        data: Object.values(data.jobs_per_day),
                        backgroundColor: '#58a6ff'
                    }]
                },
                options: {
                    responsive: true,
                    scales: { y: { beginAtZero: true, grid: { color: '#30363d' } }, x: { grid: { display: false } } },
                    plugins: { legend: { display: false } }
                }
            });

            // Confidence Distribution chart
            const confLabels = ['0.0–0.2', '0.2–0.4', '0.4–0.6', '0.6–0.8', '0.8–1.0'];
            const confData = data.confidence_distribution || [0, 0, 0, 0, 0];
            const ctx2 = document.getElementById('confidenceChart').getContext('2d');
            new Chart(ctx2, {
                type: 'bar',
                data: {
                    labels: confLabels,
                    datasets: [{
                        label: 'Jobs',
                        data: confData,
                        backgroundColor: '#4a9eff'
                    }]
                },
                options: {
                    responsive: true,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, ticks: { color: '#ccc' }, grid: { color: '#30363d' } },
                        x: { ticks: { color: '#ccc' }, grid: { display: false } }
                    }
                }
            });

            // Per Repo Table
            const repoTable = document.getElementById('repo-table');
            data.per_repo.forEach(r => {
                repoTable.innerHTML += `
                    <tr>
                        <td>${r.repo_name}</td>
                        <td>${r.total}</td>
                        <td>${(r.success_rate * 100).toFixed(0)}%</td>
                        <td>${r.avg_confidence.toFixed(2)}</td>
                    </tr>
                `;
            });

            // Error Table
            const errorTable = document.getElementById('error-table');
            data.top_errors.forEach(e => {
                errorTable.innerHTML += `
                    <tr>
                        <td style="font-family: monospace;">${e.fingerprint}</td>
                        <td>${e.count}</td>
                        <td>${(e.success_rate * 100).toFixed(0)}%</td>
                    </tr>
                `;
            });
        }
        loadAnalytics();
    </script>
    """
    return HTMLResponse(content=get_base_html("Analytics", content, "Analytics", username))


@auth_dashboard_router.get("/api/analytics")
async def get_analytics_data(request: Request):
    """Return comprehensive analytics data filtered to the current tenant."""
    tenant_id = _get_tenant_id(request)
    session = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=30)
        q = session.query(RepairJob).filter(RepairJob.timestamp >= cutoff)
        if tenant_id:
            q = q.filter(RepairJob.tenant_id == tenant_id)
        jobs = q.all()

        total_jobs = len(jobs)
        success_count = sum(1 for j in jobs if j.success)
        hours_saved = success_count  # 1 hour per success
        cost_saved = hours_saved * 150

        jobs_per_day = {}
        for j in jobs:
            day = j.timestamp.strftime("%Y-%m-%d")
            jobs_per_day[day] = jobs_per_day.get(day, 0) + 1

        per_repo_map = {}
        for j in jobs:
            if j.repo_name not in per_repo_map:
                per_repo_map[j.repo_name] = {"total": 0, "success": 0, "conf_sum": 0.0}
            per_repo_map[j.repo_name]["total"] += 1
            if j.success:
                per_repo_map[j.repo_name]["success"] += 1
            per_repo_map[j.repo_name]["conf_sum"] += j.confidence

        per_repo = []
        for repo, stats in per_repo_map.items():
            per_repo.append({
                "repo_name": repo,
                "total": stats["total"],
                "success_rate": stats["success"] / stats["total"],
                "avg_confidence": stats["conf_sum"] / stats["total"]
            })

        errors_map = {}
        for j in jobs:
            fp = j.fingerprint or "unknown"
            fp_short = fp[:8]
            if fp_short not in errors_map:
                errors_map[fp_short] = {"count": 0, "success": 0}
            errors_map[fp_short]["count"] += 1
            if j.success:
                errors_map[fp_short]["success"] += 1

        top_errors = []
        for fp, stats in errors_map.items():
            top_errors.append({
                "fingerprint": fp,
                "count": stats["count"],
                "success_rate": stats["success"] / stats["count"]
            })
        top_errors.sort(key=lambda x: x["count"], reverse=True)

        # Bucket confidence values 0-1 into 5 equal ranges for chart display
        conf_buckets = [0, 0, 0, 0, 0]
        for j in jobs:
            idx = min(4, int(j.confidence * 5))
            conf_buckets[idx] += 1

        return {
            "total_jobs": total_jobs,
            "success_count": success_count,
            "success_rate": success_count / total_jobs if total_jobs > 0 else 0.0,
            "hours_saved": hours_saved,
            "cost_saved": cost_saved,
            "jobs_per_day": jobs_per_day,
            "per_repo": per_repo,
            "top_errors": top_errors[:10],
            "confidence_distribution": conf_buckets,
            "memory_hit_count": sum(1 for j in jobs if j.source == "memory"),
            "slm_count": sum(1 for j in jobs if j.source == "slm")
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Intelligence
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/intelligence", response_class=HTMLResponse)
async def get_intelligence_page(request: Request):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    content = """
    <div class="metrics-row">
        <div class="metric-card">
            <div class="metric-label">Patterns Tracked</div>
            <div id="intel-total" class="metric-value">Loading...</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">High Risk</div>
            <div id="intel-high-risk" class="metric-value" style="color: var(--error-color)">Loading...</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Likely to Recur</div>
            <div id="intel-likely" class="metric-value" style="color: var(--warning-color)">Loading...</div>
        </div>
    </div>

    <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px">
            <h3 style="margin:0">Failure Predictions</h3>
            <p style="font-size:12px; color:#8b949e">ML-lite frequency analysis with exponential decay</p>
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Error Type</th>
                        <th>Language</th>
                        <th>Occurrences</th>
                        <th>Severity</th>
                        <th>Recurrence Score</th>
                        <th>Likely?</th>
                        <th>Repos</th>
                    </tr>
                </thead>
                <tbody id="intel-tbody"></tbody>
            </table>
            <div id="no-data-msg" style="display:none; padding:40px; text-align:center; color:#8b949e">
                No predictions yet - waiting for repair data
            </div>
        </div>
    </div>

    <script>
        async function loadPredictions() {
            const res = await fetch('/api/intelligence/predictions', {credentials: 'include'});
            const data = await res.json();

            document.getElementById('intel-total').innerText = data.total;

            const highRiskCount = data.predictions.filter(p => ['high', 'critical'].includes(p.predicted_severity)).length;
            document.getElementById('intel-high-risk').innerText = highRiskCount;

            const likelyCount = data.predictions.filter(p => p.is_likely_to_recur).length;
            document.getElementById('intel-likely').innerText = likelyCount;

            const tbody = document.getElementById('intel-tbody');
            const noData = document.getElementById('no-data-msg');
            tbody.innerHTML = '';

            if (data.predictions.length === 0) {
                noData.style.display = 'block';
                return;
            }
            noData.style.display = 'none';

            data.predictions.forEach(p => {
                const row = document.createElement('tr');

                const severityColors = {
                    'critical': '#f85149',
                    'high': '#d29922',
                    'medium': '#e3b341',
                    'low': '#3fb950'
                };
                const sevColor = severityColors[p.predicted_severity] || '#8b949e';

                const scorePct = (p.recurrence_score * 100).toFixed(0);

                const repos = p.contributing_repos.slice(0, 2).join(', ');
                const moreRepos = p.contributing_repos.length > 2 ? ` and ${p.contributing_repos.length - 2} more` : '';

                row.innerHTML = `
                    <td style="font-weight:bold">${p.error_type}</td>
                    <td><span class="badge badge-info">${p.language}</span></td>
                    <td>${p.occurrence_count}</td>
                    <td><span class="status-badge" style="color:${sevColor}; border-color:${sevColor}">${p.predicted_severity}</span></td>
                    <td>
                        <div style="display:flex; align-items:center; gap:10px">
                            <div style="background:#30363d; border-radius:4px; height:6px; width:100px">
                                <div style="background:#58a6ff; border-radius:4px; height:6px; width:${scorePct}%"></div>
                            </div>
                            <span>${p.recurrence_score.toFixed(2)}</span>
                        </div>
                    </td>
                    <td style="text-align:center">
                        ${p.is_likely_to_recur ? '<span style="color:#238636">&#10003;</span>' : '<span style="color:#8b949e">&#10007;</span>'}
                    </td>
                    <td style="font-size:12px; color:#8b949e">${repos}${moreRepos}</td>
                `;
                tbody.appendChild(row);
            });
        }
        loadPredictions();
    </script>
    """
    return HTMLResponse(content=get_base_html("Intelligence", content, "Intelligence", username))


@auth_dashboard_router.get("/api/intelligence")
async def get_intelligence_data(request: Request):
    """Calculate per-file risk analysis filtered to the current tenant."""
    tenant_id = _get_tenant_id(request)
    session = SessionLocal()
    try:
        q = session.query(RepairJob).filter(RepairJob.success == True)  # noqa: E712
        if tenant_id:
            q = q.filter(RepairJob.tenant_id == tenant_id)
        jobs = q.all()

        file_map = {}
        for j in jobs:
            if not j.patch_diff:
                continue
            for line in j.patch_diff.split('\n'):
                if line.startswith("--- a/") or line.startswith("+++ b/"):
                    fname = line[6:]
                    if fname not in file_map:
                        file_map[fname] = {"count": 0, "repo": j.repo_name}
                    file_map[fname]["count"] += 1

        results = []
        for fname, data in file_map.items():
            count = data["count"] / 2  # Each diff has 2 lines per file
            score = min(1.0, count * 0.2)  # 5 repairs = max risk 1.0
            results.append({
                "file": fname,
                "repo": data["repo"],
                "repair_count": int(count),
                "risk_score": score
            })

        results.sort(key=lambda x: x["risk_score"], reverse=True)
        high_risk = [r for r in results if r["risk_score"] > 0.6]

        return {
            "avg_risk": sum(r["risk_score"] for r in results) / len(results) if results else 0,
            "high_risk_files": high_risk[:10],
            "low_risk_count": sum(1 for r in results if r["risk_score"] <= 0.3),
            "medium_risk_count": sum(1 for r in results if 0.3 < r["risk_score"] <= 0.6)
        }
    finally:
        session.close()
