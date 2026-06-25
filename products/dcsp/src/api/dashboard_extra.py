"""
Extra dashboard SSR views: billing, settings, profile.

These routes were split out of dashboard_views.py to keep that file under the
600-line limit. They register on auth_dashboard_router (requires valid session)
and are activated when main.py imports this module.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse

from src.api.dashboard import auth_dashboard_router
from src.api.templates import get_base_html

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/billing", response_class=HTMLResponse)
async def get_billing_page(request: Request):
    """Render the billing page showing the current plan and upgrade options."""
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    # Attempt to load plan info from DB; fall back to "Free" gracefully.
    plan_name = "Free"
    plan_color = "#8b949e"
    jobs_used = 0
    jobs_limit = 50
    try:
        from src.database import SessionLocal
        from src.api.auth import get_session_tenant_id
        tenant_id = get_session_tenant_id(token)
        if tenant_id:
            from src.db.tenant_repo import get_tenant_by_id
            session = SessionLocal()
            try:
                tenant = get_tenant_by_id(session, tenant_id)
                if tenant:
                    plan_name = (tenant.plan or "free").capitalize()
                    if tenant.plan == "pro":
                        plan_color = "#58a6ff"
                        jobs_limit = 500
                    elif tenant.plan == "enterprise":
                        plan_color = "#238636"
                        jobs_limit = 9999
            except Exception as e:
                logger.warning("Could not load tenant plan for billing page: %s", e)
            finally:
                session.close()
    except Exception as e:
        logger.warning("Billing page plan lookup failed: %s", e)

    content = f"""
    <h2 style="margin-bottom:24px">Billing &amp; Plan</h2>

    <div class="card" style="border-left: 3px solid {plan_color}; display:flex; justify-content:space-between; align-items:center;">
        <div>
            <div style="font-size:13px; color:#8b949e; margin-bottom:4px">Current Plan</div>
            <div style="font-size:28px; font-weight:bold; color:{plan_color}">{plan_name}</div>
            <div style="color:#8b949e; font-size:13px; margin-top:6px">
                Up to {jobs_limit if jobs_limit < 9999 else "unlimited"} repair jobs/month
            </div>
        </div>
        <div style="text-align:right">
            <div style="font-size:13px; color:#8b949e; margin-bottom:8px">Jobs used this month</div>
            <div style="font-size:22px; font-weight:bold" id="jobs-used">--</div>
            {'<div style="color:#8b949e; font-size:12px">/ ' + str(jobs_limit) + ' included</div>' if jobs_limit < 9999 else ''}
        </div>
    </div>

    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:20px; margin-bottom:24px;">
        <div class="card" style="text-align:center; opacity:{'0.5' if plan_name.lower() == 'free' else '1'}">
            <div style="font-size:18px; font-weight:bold; margin-bottom:4px">Free</div>
            <div style="font-size:32px; font-weight:bold; margin:12px 0 4px">$0</div>
            <div style="color:#8b949e; font-size:13px; margin-bottom:16px">per month</div>
            <ul style="text-align:left; color:#8b949e; font-size:13px; list-style:none; padding:0; margin-bottom:20px">
                <li style="padding:4px 0">&#10003; 50 repair jobs / month</li>
                <li style="padding:4px 0">&#10003; 1 repository</li>
                <li style="padding:4px 0">&#10003; Community support</li>
            </ul>
            <button disabled style="width:100%; padding:10px; border-radius:6px; border:1px solid #30363d;
                background:#21262d; color:#8b949e; cursor:default; font-size:14px;">
                {'Current plan' if plan_name.lower() == 'free' else 'Downgrade'}
            </button>
        </div>

        <div class="card" style="text-align:center; border-color:#58a6ff;">
            <div style="font-size:18px; font-weight:bold; color:#58a6ff; margin-bottom:4px">Pro</div>
            <div style="font-size:32px; font-weight:bold; margin:12px 0 4px">$49</div>
            <div style="color:#8b949e; font-size:13px; margin-bottom:16px">per month</div>
            <ul style="text-align:left; color:#8b949e; font-size:13px; list-style:none; padding:0; margin-bottom:20px">
                <li style="padding:4px 0">&#10003; 500 repair jobs / month</li>
                <li style="padding:4px 0">&#10003; Unlimited repositories</li>
                <li style="padding:4px 0">&#10003; Slack &amp; email alerts</li>
                <li style="padding:4px 0">&#10003; Priority support</li>
            </ul>
            <button onclick="alert('Billing integration coming soon. Contact sales@dcsp.io.')"
                style="width:100%; padding:10px; border-radius:6px; border:none;
                background:#58a6ff; color:#0d1117; font-weight:bold; cursor:pointer; font-size:14px;">
                {'Current plan' if plan_name.lower() == 'pro' else 'Upgrade to Pro'}
            </button>
        </div>

        <div class="card" style="text-align:center; border-color:#238636;">
            <div style="font-size:18px; font-weight:bold; color:#238636; margin-bottom:4px">Enterprise</div>
            <div style="font-size:32px; font-weight:bold; margin:12px 0 4px">Custom</div>
            <div style="color:#8b949e; font-size:13px; margin-bottom:16px">per month</div>
            <ul style="text-align:left; color:#8b949e; font-size:13px; list-style:none; padding:0; margin-bottom:20px">
                <li style="padding:4px 0">&#10003; Unlimited repair jobs</li>
                <li style="padding:4px 0">&#10003; SSO / SAML</li>
                <li style="padding:4px 0">&#10003; Dedicated support SLA</li>
                <li style="padding:4px 0">&#10003; On-premise option</li>
            </ul>
            <button onclick="alert('Contact sales@dcsp.io for enterprise pricing.')"
                style="width:100%; padding:10px; border-radius:6px; border:none;
                background:#238636; color:white; font-weight:bold; cursor:pointer; font-size:14px;">
                {'Current plan' if plan_name.lower() == 'enterprise' else 'Contact Sales'}
            </button>
        </div>
    </div>

    <script>
    async function loadUsage() {{
        try {{
            const res = await fetch('/api/metrics', {{credentials: 'include'}});
            const data = await res.json();
            document.getElementById('jobs-used').textContent = data.total_jobs ?? 0;
        }} catch (err) {{
            document.getElementById('jobs-used').textContent = '?';
        }}
    }}
    loadUsage();
    </script>
    """
    return HTMLResponse(content=get_base_html("Billing", content, "Billing", username))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/settings", response_class=HTMLResponse)
async def get_settings_page(request: Request):
    """Render the notification/integration settings page."""
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    # Load current notification config from env for display defaults
    import os
    slack_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    email_to = os.environ.get("ALERT_EMAIL_TO", "")

    content = f"""
    <h2 style="margin-bottom:24px">Settings</h2>

    <div class="card">
        <h3 style="margin-top:0">Notification Settings</h3>
        <p style="color:#8b949e; font-size:14px; margin-bottom:20px">
            Configure where DCSP sends alerts when repairs succeed, fail, or are escalated.
        </p>
        <div id="settings-msg" style="display:none; margin-bottom:14px; padding:10px; border-radius:4px; font-size:13px;"></div>
        <form id="settings-form">
            <div class="form-group" style="margin-bottom:18px">
                <label style="display:block; margin-bottom:6px; font-size:14px; color:#8b949e">
                    Slack Webhook URL
                </label>
                <input type="url" id="slack-webhook" name="slack_webhook"
                    value="{slack_url}"
                    placeholder="https://hooks.slack.com/services/..."
                    style="width:100%; padding:10px; background:#0d1117; border:1px solid #30363d;
                           border-radius:6px; color:#c9d1d9; box-sizing:border-box; font-size:14px;">
                <div style="font-size:12px; color:#8b949e; margin-top:4px">
                    Leave blank to disable Slack notifications.
                </div>
            </div>
            <div class="form-group" style="margin-bottom:24px">
                <label style="display:block; margin-bottom:6px; font-size:14px; color:#8b949e">
                    Alert Email Address
                </label>
                <input type="email" id="alert-email" name="alert_email"
                    value="{email_to}"
                    placeholder="ops@yourcompany.com"
                    style="width:100%; padding:10px; background:#0d1117; border:1px solid #30363d;
                           border-radius:6px; color:#c9d1d9; box-sizing:border-box; font-size:14px;">
                <div style="font-size:12px; color:#8b949e; margin-top:4px">
                    Leave blank to disable email notifications.
                </div>
            </div>
            <button type="submit"
                style="padding:10px 24px; background:#238636; color:white; border:none;
                       border-radius:6px; font-weight:bold; cursor:pointer; font-size:14px;">
                Save Settings
            </button>
        </form>
    </div>

    <div class="card">
        <h3 style="margin-top:0">Repair Thresholds</h3>
        <p style="color:#8b949e; font-size:14px; margin-bottom:20px">
            Control when DCSP auto-applies a patch vs. escalates to a developer.
        </p>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px;">
            <div>
                <label style="display:block; margin-bottom:6px; font-size:14px; color:#8b949e">
                    Auto-apply threshold (confidence &ge;)
                </label>
                <input type="number" id="auto-threshold" min="0" max="1" step="0.05" value="0.85"
                    style="width:100%; padding:10px; background:#0d1117; border:1px solid #30363d;
                           border-radius:6px; color:#c9d1d9; box-sizing:border-box; font-size:14px;">
            </div>
            <div>
                <label style="display:block; margin-bottom:6px; font-size:14px; color:#8b949e">
                    Escalation threshold (confidence &lt;)
                </label>
                <input type="number" id="esc-threshold" min="0" max="1" step="0.05" value="0.5"
                    style="width:100%; padding:10px; background:#0d1117; border:1px solid #30363d;
                           border-radius:6px; color:#c9d1d9; box-sizing:border-box; font-size:14px;">
            </div>
        </div>
        <button onclick="alert('Threshold settings coming soon.')"
            style="margin-top:16px; padding:10px 24px; background:#21262d; color:#c9d1d9;
                   border:1px solid #30363d; border-radius:6px; cursor:pointer; font-size:14px;">
            Save Thresholds
        </button>
    </div>

    <script>
    document.getElementById('settings-form').addEventListener('submit', async function(e) {{
        e.preventDefault();
        const msg = document.getElementById('settings-msg');
        msg.style.display = 'none';
        const body = {{
            slack_webhook: document.getElementById('slack-webhook').value,
            alert_email: document.getElementById('alert-email').value,
        }};
        try {{
            const res = await fetch('/api/settings', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                credentials: 'include',
                body: JSON.stringify(body),
            }});
            if (res.ok) {{
                msg.style.cssText = 'display:block; padding:10px; border-radius:4px; font-size:13px; ' +
                    'background:rgba(35,134,54,0.15); color:#3fb950; border:1px solid rgba(35,134,54,0.4);';
                msg.textContent = 'Settings saved successfully.';
            }} else {{
                const data = await res.json().catch(() => ({{}}));
                msg.style.cssText = 'display:block; padding:10px; border-radius:4px; font-size:13px; ' +
                    'background:rgba(218,54,51,0.15); color:#f85149; border:1px solid rgba(218,54,51,0.4);';
                msg.textContent = data.detail || 'Failed to save settings.';
            }}
        }} catch (err) {{
            msg.style.cssText = 'display:block; padding:10px; border-radius:4px; font-size:13px; ' +
                'background:rgba(218,54,51,0.15); color:#f85149; border:1px solid rgba(218,54,51,0.4);';
            msg.textContent = 'Network error. Please try again.';
        }}
    }});
    </script>
    """
    return HTMLResponse(content=get_base_html("Settings", content, "Settings", username))


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/profile", response_class=HTMLResponse)
async def get_profile_page(request: Request):
    """Render the user profile page with account info and change-password form."""
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

    # Load email from DB if available
    email = ""
    role = "user"
    try:
        from src.database import SessionLocal
        from src.db.user_repo import get_user_by_username
        session = SessionLocal()
        try:
            user = get_user_by_username(session, username)
            if user:
                email = getattr(user, "email", "") or ""
                role = getattr(user, "role", "user") or "user"
        except Exception as e:
            logger.warning("Could not load user profile data for %s: %s", username, e)
        finally:
            session.close()
    except Exception as e:
        logger.warning("Profile page DB lookup failed: %s", e)

    content = f"""
    <h2 style="margin-bottom:24px">Profile</h2>

    <div class="card">
        <h3 style="margin-top:0">Account Information</h3>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:8px;">
            <div>
                <div style="font-size:13px; color:#8b949e; margin-bottom:4px">Username</div>
                <div style="font-size:16px; font-weight:bold">{username}</div>
            </div>
            <div>
                <div style="font-size:13px; color:#8b949e; margin-bottom:4px">Email</div>
                <div style="font-size:16px">{email if email else '<span style="color:#8b949e; font-style:italic">not set</span>'}</div>
            </div>
            <div>
                <div style="font-size:13px; color:#8b949e; margin-bottom:4px">Role</div>
                <div>
                    <span style="padding:3px 10px; border-radius:12px; font-size:13px; font-weight:500;
                        {'background:rgba(35,134,54,0.2); color:#3fb950; border:1px solid rgba(35,134,54,0.4)' if role == 'admin' else 'background:rgba(88,166,255,0.1); color:#58a6ff; border:1px solid rgba(88,166,255,0.3)'}">{role}</span>
                </div>
            </div>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-top:0">Change Password</h3>
        <div id="pw-msg" style="display:none; margin-bottom:14px; padding:10px; border-radius:4px; font-size:13px;"></div>
        <form id="pw-form" style="max-width:420px">
            <div style="margin-bottom:16px">
                <label style="display:block; margin-bottom:6px; font-size:14px; color:#8b949e">
                    Current password
                </label>
                <input type="password" id="old-pw" name="old_password" required
                    autocomplete="current-password"
                    style="width:100%; padding:10px; background:#0d1117; border:1px solid #30363d;
                           border-radius:6px; color:#c9d1d9; box-sizing:border-box; font-size:14px;">
            </div>
            <div style="margin-bottom:16px">
                <label style="display:block; margin-bottom:6px; font-size:14px; color:#8b949e">
                    New password <span style="font-size:12px">(min 8 chars)</span>
                </label>
                <input type="password" id="new-pw" name="new_password" required minlength="8"
                    autocomplete="new-password"
                    style="width:100%; padding:10px; background:#0d1117; border:1px solid #30363d;
                           border-radius:6px; color:#c9d1d9; box-sizing:border-box; font-size:14px;">
            </div>
            <div style="margin-bottom:20px">
                <label style="display:block; margin-bottom:6px; font-size:14px; color:#8b949e">
                    Confirm new password
                </label>
                <input type="password" id="confirm-pw" name="confirm_password" required
                    autocomplete="new-password"
                    style="width:100%; padding:10px; background:#0d1117; border:1px solid #30363d;
                           border-radius:6px; color:#c9d1d9; box-sizing:border-box; font-size:14px;">
            </div>
            <button type="submit"
                style="padding:10px 24px; background:#238636; color:white; border:none;
                       border-radius:6px; font-weight:bold; cursor:pointer; font-size:14px;">
                Update Password
            </button>
        </form>
    </div>

    <script>
    document.getElementById('pw-form').addEventListener('submit', async function(e) {{
        e.preventDefault();
        const msg = document.getElementById('pw-msg');
        msg.style.display = 'none';
        const oldPw  = document.getElementById('old-pw').value;
        const newPw  = document.getElementById('new-pw').value;
        const confPw = document.getElementById('confirm-pw').value;
        if (newPw !== confPw) {{
            msg.style.cssText = 'display:block; padding:10px; border-radius:4px; font-size:13px; ' +
                'background:rgba(218,54,51,0.15); color:#f85149; border:1px solid rgba(218,54,51,0.4);';
            msg.textContent = 'New passwords do not match.';
            return;
        }}
        try {{
            const res = await fetch('/api/profile/change-password', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                credentials: 'include',
                body: JSON.stringify({{old_password: oldPw, new_password: newPw}}),
            }});
            if (res.ok) {{
                msg.style.cssText = 'display:block; padding:10px; border-radius:4px; font-size:13px; ' +
                    'background:rgba(35,134,54,0.15); color:#3fb950; border:1px solid rgba(35,134,54,0.4);';
                msg.textContent = 'Password updated successfully.';
                document.getElementById('pw-form').reset();
            }} else {{
                const data = await res.json().catch(() => ({{}}));
                msg.style.cssText = 'display:block; padding:10px; border-radius:4px; font-size:13px; ' +
                    'background:rgba(218,54,51,0.15); color:#f85149; border:1px solid rgba(218,54,51,0.4);';
                msg.textContent = data.detail || 'Failed to update password.';
            }}
        }} catch (err) {{
            msg.style.cssText = 'display:block; padding:10px; border-radius:4px; font-size:13px; ' +
                'background:rgba(218,54,51,0.15); color:#f85149; border:1px solid rgba(218,54,51,0.4);';
            msg.textContent = 'Network error. Please try again.';
        }}
    }});
    </script>
    """
    return HTMLResponse(content=get_base_html("Profile", content, "Profile", username))
