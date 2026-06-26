"""
HTML template constants and rendering helpers for the DCSP dashboard.

All CSS, shared layout, and large HTML blocks live here so that dashboard.py
stays focused on routing logic only.

The large main-dashboard HTML (render_main_dashboard_html) was extracted to
templates_dashboard.py to keep this file under 600 lines.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shared CSS
# ---------------------------------------------------------------------------

BASE_CSS = """
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
    .container {
        max-width: 1200px;
        margin: 0 auto;
    }
    header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 20px;
        border-bottom: 1px solid var(--border-color);
        padding-bottom: 10px;
    }
    nav { display: flex; gap: 20px; }
    nav a { color: var(--text-color); text-decoration: none; font-size: 14px; font-weight: 500; }
    nav a:hover, nav a.active { color: var(--accent-color); }
    .user-info { font-size: 14px; color: #8b949e; }
    .logout-link { color: var(--accent-color); text-decoration: none; margin-left: 10px; }

    .card {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 6px;
        padding: 20px;
        margin-bottom: 20px;
    }
    table { width: 100%; border-collapse: collapse; text-align: left; }
    th, td { padding: 12px 15px; border-bottom: 1px solid var(--border-color); }
    th { background-color: #1f242c; font-size: 14px; color: #8b949e; }

    .btn {
        padding: 8px 16px;
        border-radius: 6px;
        border: 1px solid var(--border-color);
        background-color: #21262d;
        color: var(--text-color);
        cursor: pointer;
        font-size: 14px;
        text-decoration: none;
        display: inline-block;
    }
    .btn:hover { background-color: #30363d; }
    .btn-primary { background-color: var(--success-color); color: white; border-color: var(--success-color); }
    .btn-primary:hover { background-color: #2ea043; }
    .btn-danger { background-color: var(--error-color); color: white; border-color: var(--error-color); }
"""

# ---------------------------------------------------------------------------
# Shared page shell (all authenticated pages except /dashboard itself)
# ---------------------------------------------------------------------------

def get_base_html(title: str, content: str, active_tab: str, username: str) -> str:
    nav_links = [
        ("Dashboard", "/dashboard"),
        ("Analytics", "/dashboard/analytics"),
        ("Incidents", "/dashboard/incidents"),
        ("Compliance", "/dashboard/compliance"),
        ("Audit Log", "/dashboard/audit"),
        ("Intelligence", "/dashboard/intelligence"),
        ("Admin", "/dashboard/admin"),
        ("API Keys", "/dashboard/api-keys"),
        ("GitHub", "/dashboard/github"),
        ("Security", "/dashboard/security"),
        ("Billing", "/dashboard/billing"),
        ("Settings", "/dashboard/settings"),
        ("Profile", "/dashboard/profile"),
    ]
    nav_html = "".join([
        f'<a href="{url}" class="{ "active" if name == active_tab else "" }">{name}</a>'
        for name, url in nav_links
    ])

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <base href="http://139.59.87.218:8001/">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - DCSP</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        {BASE_CSS}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div style="display: flex; align-items: center; gap: 30px;">
                <h1 style="margin: 0; font-size: 20px;">DCSP</h1>
                <nav>{nav_html}</nav>
            </div>
            <div class="user-info">
                <span>Logged in as: <strong>{username}</strong></span>
                <a href="/logout" class="logout-link">Logout</a>
            </div>
        </header>
        {content}
    </div>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Re-export render_main_dashboard_html from templates_dashboard.py so that
# existing callers (dashboard.py) do not need to change their import path.
# ---------------------------------------------------------------------------
from src.api.templates_dashboard import render_main_dashboard_html  # noqa: E402,F401
