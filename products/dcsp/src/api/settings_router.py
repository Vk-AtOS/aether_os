"""
Settings endpoints for DCSP.

GET  /dashboard/settings  — SSR settings page
POST /settings/save       — save tenant settings
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src.api.dashboard import auth_dashboard_router
from src.api.templates import get_base_html
from src.database import SessionLocal
from src.models import TenantSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


def _get_or_create_settings(session, tenant_id: str) -> TenantSettings:
    """Return existing TenantSettings row, or create a blank one."""
    s = session.query(TenantSettings).filter(TenantSettings.tenant_id == tenant_id).first()
    if not s:
        s = TenantSettings(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            updated_at=datetime.utcnow(),
        )
        session.add(s)
        session.commit()
        session.refresh(s)
    return s


@auth_dashboard_router.get("/dashboard/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """SSR settings page for per-tenant configuration."""
    from src.api.auth import verify_session_token, get_session_tenant_id

    token = request.cookies.get("session_token")
    username = verify_session_token(token) or "User"
    tenant_id = get_session_tenant_id(token) or ""

    settings = None
    if tenant_id:
        session = SessionLocal()
        try:
            settings = _get_or_create_settings(session, tenant_id)
        except Exception as e:
            logger.warning("Could not load settings for tenant %s: %s", tenant_id, e)
        finally:
            session.close()

    slack_val = (settings.slack_webhook_url or "") if settings else ""
    email_val = (settings.notification_email or "") if settings else ""
    gh_client_val = (settings.github_client_id or "") if settings else ""
    threshold_val = str(settings.auto_approve_threshold if settings else 0.95)

    saved_msg = ""
    if request.query_params.get("saved"):
        saved_msg = '<div class="card" style="border-color:#238636;background:rgba(35,134,54,0.1);"><strong style="color:#3fb950">Settings saved successfully.</strong></div>'

    content = f"""
    {saved_msg}
    <div class="card">
        <h2 style="margin-top:0">Settings</h2>
        <p style="color:#8b949e">Configure notifications, integrations, and repair behaviour for your tenant.</p>
    </div>

    <form action="/settings/save" method="post">
    <div class="card">
        <h3 style="margin-top:0">Notifications</h3>

        <div style="margin-bottom:15px">
            <label style="display:block; font-size:14px; margin-bottom:5px">Slack Webhook URL</label>
            <input type="url" name="slack_webhook_url" value="{slack_val}"
                placeholder="https://hooks.slack.com/services/..."
                style="width:100%; padding:8px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; box-sizing:border-box">
            <p style="font-size:12px; color:#8b949e; margin:5px 0 0">Receive Slack alerts for every repair job.</p>
        </div>

        <div style="margin-bottom:15px">
            <label style="display:block; font-size:14px; margin-bottom:5px">Notification Email</label>
            <input type="email" name="notification_email" value="{email_val}"
                placeholder="ops@yourcompany.com"
                style="width:100%; padding:8px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; box-sizing:border-box">
            <p style="font-size:12px; color:#8b949e; margin:5px 0 0">Email address for repair notifications.</p>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-top:0">GitHub OAuth App</h3>

        <div style="margin-bottom:15px">
            <label style="display:block; font-size:14px; margin-bottom:5px">GitHub Client ID</label>
            <input type="text" name="github_client_id" value="{gh_client_val}"
                placeholder="Iv1.abc123..."
                style="width:100%; padding:8px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; box-sizing:border-box">
        </div>

        <div style="margin-bottom:15px">
            <label style="display:block; font-size:14px; margin-bottom:5px">GitHub Client Secret</label>
            <input type="password" name="github_client_secret"
                placeholder="(leave blank to keep existing value)"
                style="width:100%; padding:8px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; box-sizing:border-box">
        </div>
    </div>

    <div class="card">
        <h3 style="margin-top:0">Auto-Approve Threshold</h3>
        <div style="margin-bottom:15px">
            <label style="display:block; font-size:14px; margin-bottom:5px">
                Confidence threshold (0.0 – 1.0) above which patches are applied without human approval
            </label>
            <input type="number" name="auto_approve_threshold" value="{threshold_val}"
                min="0" max="1" step="0.01"
                style="width:200px; padding:8px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9">
            <p style="font-size:12px; color:#8b949e; margin:5px 0 0">
                Set to 1.0 to require manual approval for all patches.
                Default: 0.95.
            </p>
        </div>
    </div>

    <div style="display:flex; gap:10px; margin-top:10px">
        <button type="submit" class="btn btn-primary">Save Settings</button>
        <a href="/dashboard/settings" class="btn">Cancel</a>
    </div>
    </form>
    """
    return HTMLResponse(content=get_base_html("Settings", content, "Settings", username))


@router.post("/save")
async def save_settings(request: Request):
    """Save tenant settings from the form."""
    from src.api.auth import verify_session_token, get_session_tenant_id

    token = request.cookies.get("session_token")
    if not verify_session_token(token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tenant_id = get_session_tenant_id(token) or ""
    if not tenant_id:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/dashboard/settings?saved=1", status_code=303)

    form = await request.form()
    slack_url = form.get("slack_webhook_url", "").strip()
    notif_email = form.get("notification_email", "").strip()
    gh_client_id = form.get("github_client_id", "").strip()
    gh_client_secret = form.get("github_client_secret", "").strip()
    try:
        threshold = float(form.get("auto_approve_threshold", "0.95"))
        threshold = max(0.0, min(1.0, threshold))
    except ValueError:
        threshold = 0.95

    session = SessionLocal()
    try:
        s = _get_or_create_settings(session, tenant_id)
        s.slack_webhook_url = slack_url or None
        s.notification_email = notif_email or None
        s.github_client_id = gh_client_id or None
        if gh_client_secret:
            s.github_client_secret = gh_client_secret
        s.auto_approve_threshold = threshold
        s.updated_at = datetime.utcnow()
        session.commit()
    except Exception as e:
        logger.error("Failed to save settings for tenant %s: %s", tenant_id, e)
    finally:
        session.close()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard/settings?saved=1", status_code=303)
