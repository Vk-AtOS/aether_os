"""
Dashboard core: router definitions, login/logout, and the main /dashboard route.

All view pages live in dashboard_views.py.
Job management routes live in dashboard_jobs.py.
HTML templates and CSS constants live in templates.py.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.api.auth_router import get_current_user
from src.api.templates import render_main_dashboard_html
from src.database import SessionLocal
from src.db.audit_repo import save_audit_log

logger = logging.getLogger(__name__)

# Public routes (login, logout, landing, register, forgot/reset password)
router = APIRouter()

# Authenticated routes — dependency ensures valid session on every endpoint
auth_dashboard_router = APIRouter(dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def landing_page():
    """Public landing page — redirects authenticated users to dashboard."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DCSP — AI-Powered CI Self-Healing</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--text:#c9d1d9;--accent:#58a6ff;--green:#238636;--border:#30363d}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);line-height:1.6}
a{color:var(--accent);text-decoration:none}
.nav{display:flex;justify-content:space-between;align-items:center;padding:20px 40px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:10}
.logo{font-size:20px;font-weight:bold;letter-spacing:-0.5px}
.nav-links{display:flex;gap:20px;align-items:center;font-size:14px}
.btn{padding:8px 18px;border-radius:6px;font-weight:600;font-size:14px;display:inline-block}
.btn-primary{background:var(--green);color:#fff;border:none}
.btn-primary:hover{background:#2ea043}
.btn-outline{border:1px solid var(--border);color:var(--text)}
.btn-outline:hover{border-color:var(--accent);color:var(--accent)}
.hero{text-align:center;padding:80px 40px 60px;max-width:800px;margin:0 auto}
.badge{display:inline-block;padding:4px 12px;background:rgba(88,166,255,0.1);border:1px solid rgba(88,166,255,0.3);border-radius:20px;font-size:12px;color:var(--accent);margin-bottom:20px}
h1{font-size:clamp(32px,5vw,56px);line-height:1.2;margin-bottom:20px;letter-spacing:-1px}
h1 span{color:var(--accent)}
.hero p{font-size:18px;color:#8b949e;max-width:600px;margin:0 auto 30px}
.cta-row{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
.features{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;padding:40px;max-width:1100px;margin:0 auto}
.feature-card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:24px}
.feature-icon{font-size:28px;margin-bottom:12px}
.feature-card h3{font-size:18px;margin-bottom:8px}
.feature-card p{color:#8b949e;font-size:14px}
.pricing{padding:60px 40px;text-align:center}
.pricing h2{font-size:32px;margin-bottom:10px}
.pricing p{color:#8b949e;margin-bottom:40px}
.plans{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px;max-width:900px;margin:0 auto}
.plan{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:28px;text-align:left}
.plan.featured{border-color:var(--green)}
.plan-name{font-size:20px;font-weight:bold;margin-bottom:5px}
.plan-price{font-size:36px;font-weight:bold;margin:12px 0 4px}
.plan-period{color:#8b949e;font-size:13px;margin-bottom:16px}
.plan ul{color:#8b949e;font-size:13px;padding-left:0;list-style:none}
.plan ul li{padding:4px 0}
.plan ul li::before{content:"✓ ";color:var(--green)}
.plan .btn{width:100%;text-align:center;margin-top:20px;padding:10px}
.how-it-works{padding:60px 40px;max-width:900px;margin:0 auto}
.how-it-works h2{font-size:32px;margin-bottom:30px;text-align:center}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px}
.step{text-align:center}
.step-num{width:40px;height:40px;background:rgba(88,166,255,0.15);border:1px solid rgba(88,166,255,0.4);border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:bold;color:var(--accent);margin:0 auto 12px}
.step p{color:#8b949e;font-size:13px}
footer{border-top:1px solid var(--border);padding:30px 40px;text-align:center;color:#8b949e;font-size:13px}
</style>
</head>
<body>
<nav class="nav">
    <div class="logo">⚡ DCSP</div>
    <div class="nav-links">
        <a href="#features">Features</a>
        <a href="#pricing">Pricing</a>
        <a href="/login" class="btn btn-outline">Sign in</a>
        <a href="/register" class="btn btn-primary">Start free</a>
    </div>
</nav>

<section class="hero">
    <div class="badge">🤖 Powered by AWS Bedrock Nova Pro</div>
    <h1>AI-Powered CI <span>Self-Healing</span></h1>
    <p>DCSP fixes your broken builds automatically using LLMs. Zero human intervention for 80% of failures — patches are generated, sandboxed, and applied in seconds.</p>
    <div class="cta-row">
        <a href="/register" class="btn btn-primary" style="padding:12px 28px;font-size:16px">Start free trial</a>
        <a href="/login" class="btn btn-outline" style="padding:12px 28px;font-size:16px">View dashboard →</a>
    </div>
</section>

<section id="features" class="features">
    <div class="feature-card">
        <div class="feature-icon">🔗</div>
        <h3>Any CI System</h3>
        <p>Webhooks for GitHub Actions, GitLab CI, and Jenkins. HMAC-verified for security.</p>
    </div>
    <div class="feature-card">
        <div class="feature-icon">🧠</div>
        <h3>LLM-Powered Repair</h3>
        <p>AWS Bedrock Nova Pro generates context-aware patches. Falls back to pattern memory for known errors.</p>
    </div>
    <div class="feature-card">
        <div class="feature-icon">🏖</div>
        <h3>Sandboxed Execution</h3>
        <p>Every patch runs in a Docker sandbox before it reaches your repo. No untested code ever lands.</p>
    </div>
    <div class="feature-card">
        <div class="feature-icon">📊</div>
        <h3>10-Tab Dashboard</h3>
        <p>Analytics, compliance reports, incident tracking, security audit, and one-click patch approval.</p>
    </div>
    <div class="feature-card">
        <div class="feature-icon">🏢</div>
        <h3>Multi-Tenant SaaS</h3>
        <p>Full tenant isolation — each organisation sees only their own repair jobs and data.</p>
    </div>
    <div class="feature-card">
        <div class="feature-icon">📄</div>
        <h3>Compliance-Ready</h3>
        <p>Full audit log plus PDF/CSV compliance exports for SOC 2 and ISO 27001 readiness.</p>
    </div>
</section>

<section class="how-it-works">
    <h2>How It Works</h2>
    <div class="steps">
        <div class="step">
            <div class="step-num">1</div>
            <strong>Webhook received</strong>
            <p>CI failure triggers an HMAC-verified webhook to DCSP.</p>
        </div>
        <div class="step">
            <div class="step-num">2</div>
            <strong>Log parsed</strong>
            <p>AST analysis and log parser identify the root cause.</p>
        </div>
        <div class="step">
            <div class="step-num">3</div>
            <strong>Patch generated</strong>
            <p>Bedrock LLM generates a minimal, targeted patch.</p>
        </div>
        <div class="step">
            <div class="step-num">4</div>
            <strong>Sandbox tested</strong>
            <p>Patch runs in a Docker sandbox — zero risk to your repo.</p>
        </div>
        <div class="step">
            <div class="step-num">5</div>
            <strong>Human approval</strong>
            <p>One click to approve, or auto-approve above threshold.</p>
        </div>
        <div class="step">
            <div class="step-num">6</div>
            <strong>PR created</strong>
            <p>Approved patch opens a PR on GitHub or GitLab automatically.</p>
        </div>
    </div>
</section>

<section id="pricing" class="pricing">
    <h2>Simple Pricing</h2>
    <p>Start free. Scale as you grow.</p>
    <div class="plans">
        <div class="plan">
            <div class="plan-name">Free</div>
            <div class="plan-price">$0</div>
            <div class="plan-period">forever</div>
            <ul>
                <li>5 repairs/month</li>
                <li>GitHub &amp; GitLab</li>
                <li>Dashboard access</li>
                <li>Audit log</li>
            </ul>
            <a href="/register" class="btn btn-outline">Get started</a>
        </div>
        <div class="plan featured">
            <div class="plan-name" style="color:#3fb950">Pro</div>
            <div class="plan-price">$49</div>
            <div class="plan-period">per month</div>
            <ul>
                <li>100 repairs/month</li>
                <li>All CI systems</li>
                <li>Slack &amp; email alerts</li>
                <li>Compliance exports</li>
                <li>API key access</li>
            </ul>
            <a href="/register" class="btn btn-primary">Start Pro trial</a>
        </div>
        <div class="plan">
            <div class="plan-name" style="color:#bc8cff">Enterprise</div>
            <div class="plan-price">$199</div>
            <div class="plan-period">per month</div>
            <ul>
                <li>Unlimited repairs</li>
                <li>SAML/SSO</li>
                <li>SLA &amp; support</li>
                <li>Custom integrations</li>
                <li>Dedicated instance</li>
            </ul>
            <a href="/register" class="btn btn-outline" style="border-color:#bc8cff;color:#bc8cff">Contact us</a>
        </div>
    </div>
</section>

<footer>
    <p>© 2025 DCSP · <a href="/login">Sign in</a> · <a href="/register">Create account</a></p>
</footer>
</body>
</html>"""
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    """Serve the login page."""
    error = request.query_params.get("error")
    error_msg = ""
    if error:
        error_msg = '<p style="color: var(--error-color); text-align: center;">Invalid username or password</p>'

    if error:
        try:
            session = SessionLocal()
            save_audit_log(
                session, "login_failed", "unknown",
                details="Invalid credentials",
                ip_address=request.client.host
            )
            session.close()
        except Exception as e:
            logger.warning("Could not write login_failed audit log: %s", e)

    html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DCSP Login</title>
    <style>
        :root { --bg-color: #0d1117; --card-bg: #161b22; --text-color: #c9d1d9; --accent-color: #58a6ff; --success-color: #238636; --error-color: #da3633; --border-color: #30363d; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; background-color: var(--bg-color); color: var(--text-color); display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .login-card { background-color: var(--card-bg); border: 1px solid var(--border-color); border-radius: 6px; padding: 40px; width: 100%; max-width: 400px; box-shadow: 0 8px 24px rgba(0,0,0,0.5); }
        h1 { text-align: center; margin-bottom: 30px; font-size: 24px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 8px; font-size: 14px; color: #8b949e; }
        input { width: 100%; padding: 10px; background-color: var(--bg-color); border: 1px solid var(--border-color); border-radius: 6px; color: var(--text-color); box-sizing: border-box; }
        button { width: 100%; padding: 12px; background-color: var(--success-color); color: white; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; margin-top: 10px; }
        button:hover { background-color: #2ea043; }
    </style>
</head>
<body>
    <div class="login-card">
        <h1>DCSP Login</h1>
        {error_msg}
        <form action="/auth/login" method="post">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required autocomplete="username">
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required autocomplete="current-password">
            </div>
            <button type="submit">Sign In</button>
        </form>
        <div style="margin-top: 20px; text-align: center; font-size: 14px; color: #8b949e; display: flex; justify-content: center; gap: 20px;">
            <a href="/auth/forgot-password" style="color: #58a6ff; text-decoration: none;">Forgot password?</a>
            <a href="/register" style="color: #58a6ff; text-decoration: none;">Create account</a>
        </div>
    </div>
</body>
</html>
    """
    reset_msg = ""
    if request.query_params.get("reset"):
        reset_msg = '<p style="color: var(--success-color); text-align: center;">Password reset successful. Please log in.</p>'
    return HTMLResponse(content=html_template.replace("{error_msg}", error_msg + reset_msg))


@router.get("/logout")
async def logout():
    """Clear session and redirect to login."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session_token")
    return response


# ---------------------------------------------------------------------------
# Main dashboard home
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    token = request.cookies.get("session_token")
    from src.api.auth import verify_session_token
    username = verify_session_token(token) or "User"

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
        f'<a href="{url}" class="{ "active" if name == "Dashboard" else "" }">{name}</a>'
        for name, url in nav_links
    ])

    return HTMLResponse(content=render_main_dashboard_html(username, nav_html))
