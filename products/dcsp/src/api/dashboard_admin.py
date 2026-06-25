"""
Dashboard admin and API-key management routes.

Extracted from dashboard_views.py to keep file sizes under 600 lines.
Routes registered on auth_dashboard_router (imported from dashboard.py).
This module is imported by main.py so the routes self-register.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse

from src.api.dashboard import auth_dashboard_router
from src.api.templates import get_base_html
from src.database import SessionLocal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/admin", response_class=HTMLResponse)
async def get_admin_page(request: Request):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    session = SessionLocal()
    try:
        from src.db.tenant_repo import list_tenants
        tenants = list_tenants(session, active_only=False)
        tenant_rows = ""
        for t in tenants:
            plan_badge_color = {
                "free": "#8b949e",
                "pro": "#58a6ff",
                "enterprise": "#238636"
            }.get(t.plan, "#8b949e")
            status = "Active" if t.is_active else "Inactive"
            status_color = "#238636" if t.is_active else "#da3633"
            tenant_rows += f"""
            <tr>
                <td>{t.name}</td>
                <td><code>{t.slug}</code></td>
                <td><span style="color:{plan_badge_color}; font-weight:bold">{t.plan}</span></td>
                <td><span style="color:{status_color}">{status}</span></td>
                <td style="font-size:12px;color:#8b949e">{t.created_at.strftime("%Y-%m-%d %H:%M")}</td>
                <td>
                    <button onclick="changePlan('{t.id}', '{t.plan}')" class="btn" style="padding:4px 8px; font-size:12px">
                        Change Plan
                    </button>
                </td>
            </tr>"""
    finally:
        session.close()

    content = f"""
    <div class="card">
        <h2 style="margin-top:0">System Administration</h2>
        <p style="color:#8b949e">Manage tenants, plans, and system configuration.</p>
    </div>

    <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px">
            <h3 style="margin:0">Tenants</h3>
            <button onclick="showCreateTenant()" class="btn btn-primary">+ New Tenant</button>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Slug</th>
                    <th>Plan</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody id="tenant-tbody">
                {tenant_rows}
            </tbody>
        </table>
    </div>

    <div id="create-tenant-modal"
        style="display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);
        background:#161b22;border:1px solid #30363d;border-radius:8px;padding:30px;min-width:400px;z-index:1000">
        <h3 style="margin-top:0">Create New Tenant</h3>
        <div style="margin-bottom:15px">
            <label style="display:block; margin-bottom:5px;font-size:14px">Name</label>
            <input id="new-tenant-name" type="text" placeholder="Company Name"
                style="width:100%;padding:8px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;box-sizing:border-box">
        </div>
        <div style="margin-bottom:20px">
            <label style="display:block; margin-bottom:5px;font-size:14px">Plan</label>
            <select id="new-tenant-plan"
                style="width:100%;padding:8px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9">
                <option value="free">Free</option>
                <option value="pro">Pro</option>
                <option value="enterprise">Enterprise</option>
            </select>
        </div>
        <div style="display:flex;gap:10px">
            <button onclick="createTenant()" class="btn btn-primary">Create</button>
            <button onclick="hideCreateTenant()" class="btn">Cancel</button>
        </div>
    </div>

    <script>
    function showCreateTenant() {{
        document.getElementById('create-tenant-modal').style.display = 'block';
    }}
    function hideCreateTenant() {{
        document.getElementById('create-tenant-modal').style.display = 'none';
    }}
    async function createTenant() {{
        const name = document.getElementById('new-tenant-name').value;
        const plan = document.getElementById('new-tenant-plan').value;
        if (!name) {{
            alert('Name is required');
            return;
        }}
        const res = await fetch('/admin/tenants', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            credentials: 'include',
            body: JSON.stringify({{name, plan}})
        }});
        if (res.ok) {{
            hideCreateTenant();
            location.reload();
        }} else {{
            const err = await res.json();
            alert('Error: ' + err.detail);
        }}
    }}
    async function changePlan(tenantId, current) {{
        const plans = ['free','pro','enterprise'];
        const plan = prompt('New plan (free/pro/enterprise):', current);
        if (!plan || !plans.includes(plan)) return;
        const res = await fetch(`/admin/tenants/${{tenantId}}/plan`, {{
            method: 'PATCH',
            headers: {{'Content-Type': 'application/json'}},
            credentials: 'include',
            body: JSON.stringify({{plan}})
        }});
        if (res.ok) location.reload();
        else alert('Failed to update plan');
    }}
    </script>
    """

    return HTMLResponse(content=get_base_html("Admin", content, "Admin", username))


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/api-keys", response_class=HTMLResponse)
async def get_api_keys_page(request: Request):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    session = SessionLocal()
    try:
        from src.db.tenant_repo import list_tenants
        tenants = list_tenants(session)
        tenant_options = "".join([
            f'<option value="{t.slug}">{t.name}</option>'
            for t in tenants
        ])
    finally:
        session.close()

    content = f"""
    <div class="card">
        <h2 style="margin-top:0">API Keys</h2>
        <p style="color:#8b949e">Manage programmatic access keys. Keys are shown only once at creation.</p>
    </div>

    <div class="card">
        <h3 style="margin-top:0">Create New Key</h3>
        <div style="display:grid; grid-template-columns:1fr 1fr 1fr auto; gap:10px;align-items:end">
            <div>
                <label style="display:block; font-size:13px;margin-bottom:4px">Key Name</label>
                <input id="key-name" type="text" placeholder="e.g. CI Pipeline Key"
                    style="width:100%;padding:8px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;box-sizing:border-box">
            </div>
            <div>
                <label style="display:block; font-size:13px;margin-bottom:4px">Tenant</label>
                <select id="key-tenant"
                    style="width:100%;padding:8px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9">
                    {tenant_options}
                </select>
            </div>
            <div>
                <label style="display:block; font-size:13px;margin-bottom:4px">Expires (optional)</label>
                <input id="key-expires" type="date"
                    style="width:100%;padding:8px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;box-sizing:border-box">
            </div>
            <button onclick="createKey()" class="btn btn-primary" style="padding:8px 16px">Generate Key</button>
        </div>
    </div>

    <div id="new-key-banner" style="display:none" class="card">
        <div style="display:flex; align-items:center;gap:10px;margin-bottom:10px">
            <span style="color:#238636; font-size:18px">&#10003;</span>
            <strong>Key created successfully. Copy it now - it will not be shown again.</strong>
        </div>
        <div style="display:flex;gap:10px; align-items:center">
            <code id="new-key-value"
                style="background:#0d1117;padding:10px 15px;border-radius:4px;border:1px solid #238636;flex:1;font-size:13px;word-break:break-all">
            </code>
            <button onclick="copyKey()" class="btn" style="white-space:nowrap">Copy Key</button>
        </div>
    </div>

    <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px">
            <h3 style="margin:0">Active Keys</h3>
            <select id="filter-tenant" onchange="loadKeys()"
                style="padding:6px 10px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9">
                {tenant_options}
            </select>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Prefix</th>
                    <th>Created</th>
                    <th>Last Used</th>
                    <th>Expires</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody id="keys-tbody"></tbody>
        </table>
    </div>

    <script>
    async function loadKeys() {{
        const tenant = document.getElementById('filter-tenant').value;
        const res = await fetch(`/admin/api-keys?tenant_slug=${{tenant}}`, {{credentials: 'include'}});
        const keys = await res.json();
        const tbody = document.getElementById('keys-tbody');
        tbody.innerHTML = '';
        if (!keys.length) {{
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#8b949e">No keys found</td></tr>';
            return;
        }}
        keys.forEach(k => {{
            const row = document.createElement('tr');
            const created = new Date(k.created_at).toLocaleDateString();
            const lastUsed = k.last_used_at ? new Date(k.last_used_at).toLocaleDateString() : '<span style="color:#8b949e">Never</span>';
            const expires = k.expires_at ? new Date(k.expires_at).toLocaleDateString() : '<span style="color:#8b949e">Never</span>';
            row.innerHTML = `
                <td>${{k.name}}</td>
                <td><code>${{k.key_prefix}}...</code></td>
                <td>${{created}}</td>
                <td>${{lastUsed}}</td>
                <td>${{expires}}</td>
                <td><button class="action-btn btn-reject" onclick="revokeKey('${{k.id}}')">Revoke</button></td>`;
            tbody.appendChild(row);
        }});
    }}

    async function createKey() {{
        const name = document.getElementById('key-name').value;
        const tenant_slug = document.getElementById('key-tenant').value;
        const expires = document.getElementById('key-expires').value;
        if (!name) {{
            alert('Key name is required');
            return;
        }}
        const body = {{name, tenant_slug}};
        if (expires) body.expires_at = new Date(expires).toISOString();
        const res = await fetch('/admin/api-keys', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            credentials: 'include',
            body: JSON.stringify(body)
        }});
        const data = await res.json();
        if (res.ok) {{
            document.getElementById('new-key-value').textContent = data.key;
            document.getElementById('new-key-banner').style.display = 'block';
            document.getElementById('key-name').value = '';
            loadKeys();
        }} else {{
            alert('Error: ' + (data.detail || 'Failed to create key'));
        }}
    }}
    window.createKey = createKey;

    async function revokeKey(keyId) {{
        const tenant = document.getElementById('filter-tenant').value;
        if (!confirm('Revoke this API key? This cannot be undone.')) return;
        const res = await fetch(`/admin/api-keys/${{keyId}}?tenant_slug=${{tenant}}`, {{
            method: 'DELETE',
            credentials: 'include'
        }});
        if (res.ok) loadKeys();
        else alert('Failed to revoke key');
    }}

    function copyKey() {{
        const key = document.getElementById('new-key-value').textContent;
        navigator.clipboard.writeText(key);
    }}

    loadKeys();
    </script>
    """

    return HTMLResponse(content=get_base_html("API Keys", content, "API Keys", username))
