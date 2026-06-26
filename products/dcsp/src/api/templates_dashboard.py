"""
Dashboard HTML/CSS structure template for the DCSP main /dashboard page.

JavaScript strings are in templates_dashboard_js.py to stay under 600 lines.
"""

from __future__ import annotations

from src.api.templates_dashboard_js import (
    DASHBOARD_MAIN_JS,
    DASHBOARD_WS_JS,
    DASHBOARD_POLL_JS,
)

# ---------------------------------------------------------------------------
# CSS for the main dashboard (separate from BASE_CSS in templates.py because
# this page has extra components: detail panel, diff viewer, editor, overlay).
# ---------------------------------------------------------------------------

DASHBOARD_CSS = """
    :root {
        --bg-color: #0d1117;
        --card-bg: #161b22;
        --text-color: #c9d1d9;
        --accent-color: #58a6ff;
        --success-color: #238636;
        --error-color: #da3633;
        --warning-color: #d29922;
        --border-color: #30363d;
    }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        background-color: var(--bg-color);
        color: var(--text-color);
        margin: 0;
        padding: 20px;
        overflow-x: hidden;
    }
    .container { max-width: 1200px; margin: 0 auto; }
    header {
        display: flex; align-items: center; justify-content: space-between;
        margin-bottom: 20px; border-bottom: 1px solid var(--border-color); padding-bottom: 10px;
    }
    nav { display: flex; gap: 20px; }
    nav a { color: var(--text-color); text-decoration: none; font-size: 14px; font-weight: 500; }
    nav a:hover, nav a.active { color: var(--accent-color); }
    .user-info { font-size: 14px; color: #8b949e; }
    .logout-link { color: var(--accent-color); text-decoration: none; margin-left: 10px; }

    .status-panel {
        display: flex; gap: 20px; margin-bottom: 20px;
        background-color: var(--card-bg); border: 1px solid var(--border-color);
        border-radius: 6px; padding: 15px 20px; font-size: 14px;
    }
    .status-item { display: flex; align-items: center; }
    .status-dot-small { height: 8px; width: 8px; border-radius: 50%; display: inline-block; margin-right: 8px; }
    .dot-green { background-color: var(--success-color); box-shadow: 0 0 5px var(--success-color); }
    .dot-red { background-color: var(--error-color); box-shadow: 0 0 5px var(--error-color); }

    .metrics-row {
        display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 20px; margin-bottom: 30px;
    }
    .metric-card {
        background-color: var(--card-bg); border: 1px solid var(--border-color);
        border-radius: 6px; padding: 20px; text-align: center;
    }
    .metric-value { font-size: 24px; font-weight: bold; color: var(--accent-color); margin-top: 10px; }
    .metric-label { font-size: 14px; color: #8b949e; }

    .table-container {
        background-color: var(--card-bg); border: 1px solid var(--border-color);
        border-radius: 6px; overflow-x: auto;
    }
    table { width: 100%; border-collapse: collapse; text-align: left; }
    th, td { padding: 12px 15px; border-bottom: 1px solid var(--border-color); }
    th { background-color: #1f242c; font-size: 14px; color: #8b949e; }

    .status-badge { padding: 4px 8px; border-radius: 12px; font-size: 12px; font-weight: 500; }
    .status-success { background-color: rgba(35, 134, 54, 0.2); color: #3fb950; border: 1px solid rgba(35, 134, 54, 0.4); }
    .status-escalated { background-color: rgba(210, 153, 34, 0.2); color: #d29922; border: 1px solid rgba(210, 153, 34, 0.4); }
    .status-failed { background-color: rgba(218, 54, 51, 0.2); color: #f85149; border: 1px solid rgba(218, 54, 51, 0.4); }

    .action-btn {
        padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer;
        margin-right: 5px; border: 1px solid var(--border-color); background: transparent;
        color: var(--text-color);
    }
    .btn-approve:hover { background-color: var(--success-color); color: white; border-color: var(--success-color); }
    .btn-reject:hover { background-color: var(--error-color); color: white; border-color: var(--error-color); }
    .status-text-approved { color: var(--success-color); font-weight: bold; }
    .status-text-rejected { color: var(--error-color); font-weight: bold; }

    #detail-panel {
        position: fixed; top: 0; right: 0; width: 600px; height: 100%;
        background-color: var(--card-bg); border-left: 1px solid var(--border-color);
        box-shadow: -5px 0 15px rgba(0,0,0,0.5); transform: translateX(100%);
        transition: transform 0.3s ease-in-out; z-index: 1000;
        display: flex; flex-direction: column; padding: 0;
    }
    #detail-panel.open { transform: translateX(0); }
    .panel-header { padding: 20px; border-bottom: 1px solid var(--border-color); position: relative; }
    .close-btn { position: absolute; top: 15px; right: 15px; cursor: pointer; font-size: 24px; color: #8b949e; }
    .panel-content { padding: 20px; overflow-y: auto; flex-grow: 1; }
    .panel-section { margin-bottom: 25px; }
    .panel-section-title {
        font-size: 12px; color: #8b949e; text-transform: uppercase;
        margin-bottom: 10px; font-weight: bold; letter-spacing: 0.5px;
    }
    .badge { padding: 2px 6px; border-radius: 4px; font-size: 11px; margin-right: 5px; display: inline-block; }
    .badge-info { background-color: rgba(88, 166, 255, 0.1); color: var(--accent-color); border: 1px solid rgba(88, 166, 255, 0.2); }
    .badge-slm { background-color: rgba(187, 128, 255, 0.1); color: #bc8cff; border: 1px solid rgba(187, 128, 255, 0.2); }
    .badge-memory { background-color: rgba(187, 128, 255, 0.2); color: #bc8cff; border: 1px solid #bc8cff; }
    .diff-container {
        background-color: #0d1117; border-radius: 6px; padding: 10px;
        font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace;
        font-size: 12px; overflow-x: auto; white-space: pre; line-height: 1.4;
    }
    .diff-add { color: #3fb950; }
    .diff-remove { color: #f85149; }
    .diff-context { color: #8b949e; }
    .violation-item {
        border: 1px solid var(--error-color); background-color: rgba(218, 54, 51, 0.1);
        color: #f85149; padding: 8px; border-radius: 4px; margin-bottom: 5px; font-size: 12px;
    }
    #overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0,0,0,0.5); display: none; z-index: 999;
    }
    #overlay.open { display: block; }
    #patch-editor {
        width: 100%; min-height: 300px; background-color: #0d1117; color: #c9d1d9;
        border: 1px solid var(--border-color); border-radius: 6px; font-family: monospace;
        padding: 10px; box-sizing: border-box; resize: vertical;
    }
    .editor-container { display: none; }
    tr.job-row { cursor: pointer; }
    tr.job-row:hover { background-color: rgba(88, 166, 255, 0.05); }
    @media (max-width: 600px) {
        header { flex-direction: column; align-items: flex-start; }
        .metrics-row { grid-template-columns: 1fr 1fr; }
        #detail-panel { width: 100%; }
    }
"""

# ---------------------------------------------------------------------------
# HTML structure for the main dashboard page body
# ---------------------------------------------------------------------------

_PANEL_HTML = """
    <div id="overlay"></div>
    <div id="detail-panel">
        <div class="panel-header">
            <span class="close-btn" onclick="closePanel()">&times;</span>
            <h2 id="panel-repo" style="margin: 0; font-size: 18px;"></h2>
            <div id="panel-meta" style="margin-top: 8px;"></div>
        </div>
        <div class="panel-content">
            <div class="panel-section">
                <div class="panel-section-title">Status Overview</div>
                <div id="panel-status-row"></div>
            </div>
            <div class="panel-section">
                <div class="panel-section-title">Repair Explanation</div>
                <p id="panel-explanation" style="font-size: 14px; line-height: 1.5; margin: 0;"></p>
            </div>
            <details class="panel-section" open>
                <summary class="panel-section-title" style="cursor: pointer;">Root Cause Analysis</summary>
                <div id="panel-root-cause" style="font-size: 13px; background: rgba(255,255,255,0.03); padding: 10px; border-radius: 4px; margin-top: 10px;"></div>
            </details>
            <div class="panel-section">
                <div class="panel-section-title">Verified Patch Diff</div>
                <div id="panel-diff-view">
                    <div id="panel-diff"></div>
                    <button id="btn-edit-patch" class="btn" style="margin-top: 10px; width: 100%;" onclick="toggleEditor()">Edit Patch</button>
                </div>
                <div id="panel-editor-view" class="editor-container">
                    <textarea id="patch-editor"></textarea>
                    <div style="margin-top: 10px; display: flex; gap: 10px;">
                        <button class="btn btn-primary" style="flex: 1;" onclick="approveWithEdits()">Approve with Edits</button>
                        <button class="btn" style="flex: 1;" onclick="toggleEditor()">Cancel</button>
                    </div>
                </div>
            </div>
            <div id="panel-violations-section" class="panel-section" style="display: none;">
                <div class="panel-section-title">Stability Violations</div>
                <div id="panel-violations"></div>
            </div>
        </div>
        <div id="panel-actions" style="padding: 20px; border-top: 1px solid var(--border-color); background-color: #1f242c; display: flex; justify-content: space-between;"></div>
    </div>"""

_STATUS_METRICS_HTML = """
        <div class="status-panel">
            <div class="status-item">
                <span id="ollama-dot" class="status-dot-small dot-red"></span>
                <span>Bedrock: <span id="ollama-status">Checking...</span></span>
            </div>
            <div style="width: 20px;"></div>
            <div class="status-item">
                <span id="db-dot" class="status-dot-small dot-red"></span>
                <span>Database: <span id="db-status">Checking...</span></span>
            </div>
            <div style="width: 20px;"></div>
            <div class="status-item">
                <span>Queue Depth: <strong id="queue-depth">0</strong></span>
            </div>
            <div style="width: 20px;"></div>
            <div class="status-item">
                <span>Notifications: </span>
                <span id="slack-status" style="margin-left: 10px;">Slack: &mdash;</span>
                <span id="email-status" style="margin-left: 10px;">Email: &mdash;</span>
            </div>
        </div>
        <div class="metrics-row">
            <div class="metric-card">
                <div class="metric-label">Total Jobs</div>
                <div id="total-jobs-count" class="metric-value">0</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Success Rate</div>
                <div id="success-rate" class="metric-value">0%</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Avg Confidence</div>
                <div id="avg-confidence" class="metric-value">0.0</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Escalation Rate</div>
                <div id="escalation-rate" class="metric-value">0%</div>
            </div>
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>Repository</th>
                        <th>Confidence</th>
                        <th>Sandbox</th>
                        <th>Status</th>
                        <th>Explanation</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="jobs-tbody"></tbody>
            </table>
        </div>"""


def render_main_dashboard_html(username: str, nav_html: str) -> str:
    """Return the complete HTML for the /dashboard home page."""
    return (
        f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <base href="http://REDACTED_IP:8001/">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DCSP Dashboard</title>
    <style>{DASHBOARD_CSS}</style>
</head>
<body>
{_PANEL_HTML}
    <div class="container">
        <header>
            <div style="display: flex; align-items: center; gap: 30px;">
                <h1 style="margin: 0; font-size: 20px;">DCSP</h1>
                <nav>{nav_html}</nav>
                <span id="ws-status" style="font-size:12px;color:#d29922;margin-left:20px;">&#9675; Connecting...</span>
            </div>
            <div class="user-info">
                <span>Logged in as: <strong>{username}</strong></span>
                <a href="/logout" class="logout-link">Logout</a>
            </div>
        </header>
{_STATUS_METRICS_HTML}
    </div>
"""
        + DASHBOARD_MAIN_JS
        + DASHBOARD_WS_JS
        + DASHBOARD_POLL_JS
        + "\n</body>\n</html>\n"
    )
