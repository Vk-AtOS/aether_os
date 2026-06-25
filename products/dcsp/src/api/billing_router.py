"""
Billing endpoints for DCSP.

POST /billing/checkout  — create a Stripe checkout session
POST /billing/webhook   — receive Stripe webhook events (no auth, verified by signature)
GET  /billing/status    — return current subscription status for the authenticated user's tenant
GET  /dashboard/billing — SSR billing page
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from src.api.dashboard import auth_dashboard_router
from src.api.templates import get_base_html

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

_BILLING_NOT_CONFIGURED = JSONResponse(
    {"error": "Billing not configured — set STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET"},
    status_code=503,
)


def _billing_available() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


# ---------------------------------------------------------------------------
# Public billing endpoints
# ---------------------------------------------------------------------------

@router.post("/checkout")
async def create_checkout(request: Request):
    """Redirect authenticated user to Stripe Checkout for a plan upgrade."""
    from src.api.auth import verify_session_token, get_session_tenant_id

    token = request.cookies.get("session_token")
    if not verify_session_token(token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if not _billing_available():
        return _BILLING_NOT_CONFIGURED

    body = await request.json()
    plan = body.get("plan", "pro")
    tenant_id = get_session_tenant_id(token) or ""

    base_url = str(request.base_url).rstrip("/")
    success_url = f"{base_url}/dashboard/billing?success=1"
    cancel_url = f"{base_url}/dashboard/billing?cancelled=1"

    from src.billing import create_checkout_session
    result = create_checkout_session(tenant_id, plan, success_url, cancel_url)

    if "error" in result:
        return JSONResponse({"error": result["error"]}, status_code=502)

    return RedirectResponse(url=result["url"], status_code=303)


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Receive and verify Stripe webhook events. No session auth — verified by Stripe signature."""
    if not _billing_available():
        return _BILLING_NOT_CONFIGURED

    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    from src.billing import handle_stripe_webhook
    result = handle_stripe_webhook(payload, sig_header)

    if "error" in result:
        return JSONResponse({"error": result["error"]}, status_code=400)

    return JSONResponse(result)


@router.get("/status")
async def billing_status(request: Request):
    """Return subscription status for the current user's tenant."""
    from src.api.auth import verify_session_token, get_session_tenant_id

    token = request.cookies.get("session_token")
    if not verify_session_token(token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tenant_id = get_session_tenant_id(token) or ""
    from src.billing import get_subscription_status
    return get_subscription_status(tenant_id)


# ---------------------------------------------------------------------------
# SSR billing dashboard page
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/billing", response_class=HTMLResponse)
async def billing_page(request: Request):
    """SSR billing page showing current plan, usage, and upgrade options."""
    from src.api.auth import verify_session_token, get_session_tenant_id

    token = request.cookies.get("session_token")
    username = verify_session_token(token) or "User"
    tenant_id = get_session_tenant_id(token) or ""

    success_msg = ""
    if request.query_params.get("success"):
        success_msg = '<div class="card" style="border-color:#238636;background:rgba(35,134,54,0.1);"><strong style="color:#3fb950">Payment successful! Your plan has been upgraded.</strong></div>'
    if request.query_params.get("cancelled"):
        success_msg = '<div class="card" style="border-color:#d29922;background:rgba(210,153,34,0.1);"><strong style="color:#e3b341">Payment cancelled. Your plan was not changed.</strong></div>'

    billing_configured = _billing_available()
    from src.billing import get_subscription_status, PLAN_LIMITS
    status = get_subscription_status(tenant_id)
    current_plan = status.get("plan", "free")
    limit = PLAN_LIMITS.get(current_plan)
    limit_text = str(limit) if limit is not None else "Unlimited"

    stripe_note = "" if billing_configured else """
    <div class="card" style="border-color:#d29922;background:rgba(210,153,34,0.1)">
        <strong style="color:#e3b341">Billing not configured</strong>
        <p style="margin:5px 0 0;font-size:13px;color:#8b949e">
            Set <code>STRIPE_SECRET_KEY</code> and <code>STRIPE_WEBHOOK_SECRET</code>
            environment variables to enable billing.
        </p>
    </div>"""

    # Pre-compute conditional strings to avoid backslash-in-f-string (Python 3.11)
    plan_status_text = status.get("status", "active")

    free_border = "border-color:#58a6ff" if current_plan == "free" else ""
    free_badge = '<div style="margin-top:20px; padding:8px; background:rgba(88,166,255,0.1); border-radius:4px; color:#58a6ff; font-weight:bold">Current Plan</div>' if current_plan == "free" else ""

    pro_border = "border-color:#58a6ff" if current_plan == "pro" else "border-color:#238636"
    disable_attr = ' disabled' if not billing_configured else ""
    if current_plan == "pro":
        pro_cta = '<div style="margin-top:20px; padding:8px; background:rgba(88,166,255,0.1); border-radius:4px; color:#58a6ff; font-weight:bold">Current Plan</div>'
    else:
        pro_cta = f'<button onclick="upgrade(\'pro\')" class="btn btn-primary" style="margin-top:20px; width:100%"{disable_attr}>Upgrade to Pro</button>'

    ent_border = "border-color:#58a6ff" if current_plan == "enterprise" else ""
    if current_plan == "enterprise":
        ent_cta = '<div style="margin-top:20px; padding:8px; background:rgba(88,166,255,0.1); border-radius:4px; color:#58a6ff; font-weight:bold">Current Plan</div>'
    else:
        ent_cta = f'<button onclick="upgrade(\'enterprise\')" class="btn" style="margin-top:20px; width:100%; border-color:#bc8cff; color:#bc8cff"{disable_attr}>Upgrade to Enterprise</button>'

    content = f"""
    {success_msg}
    {stripe_note}

    <div class="card">
        <h2 style="margin-top:0">Current Plan</h2>
        <div style="display:flex; align-items:center; gap:20px">
            <div style="font-size:36px; font-weight:bold; color:#58a6ff; text-transform:uppercase">{current_plan}</div>
            <div>
                <div style="color:#8b949e; font-size:14px">Repair Limit</div>
                <div style="font-size:20px; font-weight:bold">{limit_text} repairs/month</div>
            </div>
        </div>
    </div>

    <div class="metrics-row">
        <div class="metric-card">
            <div class="metric-label">Plan</div>
            <div class="metric-value" style="font-size:20px; text-transform:uppercase">{current_plan}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Monthly Limit</div>
            <div class="metric-value" style="font-size:20px">{limit_text}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Status</div>
            <div class="metric-value" style="font-size:20px; color:#3fb950">{plan_status_text}</div>
        </div>
    </div>

    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:20px;">

        <div class="card" style="text-align:center; {free_border}">
            <h3 style="margin-top:0">Free</h3>
            <div style="font-size:36px; font-weight:bold; margin:15px 0">$0</div>
            <div style="color:#8b949e; margin-bottom:20px">per month</div>
            <ul style="text-align:left; color:#8b949e; font-size:14px; padding-left:20px">
                <li>5 repairs/month</li>
                <li>GitHub &amp; GitLab webhooks</li>
                <li>SSR dashboard</li>
                <li>Basic audit log</li>
            </ul>
            {free_badge}
        </div>

        <div class="card" style="text-align:center; {pro_border}">
            <h3 style="margin-top:0; color:#3fb950">Pro</h3>
            <div style="font-size:36px; font-weight:bold; margin:15px 0">$49</div>
            <div style="color:#8b949e; margin-bottom:20px">per month</div>
            <ul style="text-align:left; color:#8b949e; font-size:14px; padding-left:20px">
                <li>100 repairs/month</li>
                <li>All CI systems</li>
                <li>Slack notifications</li>
                <li>Compliance PDF exports</li>
                <li>API key access</li>
            </ul>
            {pro_cta}
        </div>

        <div class="card" style="text-align:center; {ent_border}">
            <h3 style="margin-top:0; color:#bc8cff">Enterprise</h3>
            <div style="font-size:36px; font-weight:bold; margin:15px 0">$199</div>
            <div style="color:#8b949e; margin-bottom:20px">per month</div>
            <ul style="text-align:left; color:#8b949e; font-size:14px; padding-left:20px">
                <li>Unlimited repairs</li>
                <li>SAML/SSO</li>
                <li>Dedicated support</li>
                <li>SLA guarantee</li>
                <li>Custom integrations</li>
            </ul>
            {ent_cta}
        </div>
    </div>

    <script>
    async function upgrade(plan) {{
        const res = await fetch('/billing/checkout', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            credentials: 'include',
            body: JSON.stringify({{plan}})
        }});
        if (res.redirected) {{
            window.location.href = res.url;
        }} else {{
            const data = await res.json();
            if (data.error) alert('Error: ' + data.error);
        }}
    }}
    </script>
    """
    return HTMLResponse(content=get_base_html("Billing", content, "Billing", username))
