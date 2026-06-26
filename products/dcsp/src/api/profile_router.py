"""
Profile endpoints for DCSP.

GET  /dashboard/profile          — SSR profile page
POST /profile/update-name        — change display name
POST /profile/change-password    — change password (current → new)
GET  /register                   — registration page
POST /auth/register               — create account
GET  /auth/forgot-password       — forgot password page
POST /auth/forgot-password       — request password reset link
GET  /auth/reset-password/{tok}  — show reset form
POST /auth/reset-password/{tok}  — submit new password
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from src.api.dashboard import auth_dashboard_router, router as public_router
from src.api.templates import get_base_html
from src.database import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["profile"])


# ---------------------------------------------------------------------------
# Profile page (I2)
# ---------------------------------------------------------------------------

@auth_dashboard_router.get("/dashboard/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    from src.api.auth import verify_session_token, get_session_tenant_id
    from src.db.user_repo import get_user_by_username
    from src.db.api_key_repo import list_api_keys_for_tenant

    token = request.cookies.get("session_token")
    username = verify_session_token(token) or "User"
    tenant_id = get_session_tenant_id(token) or ""

    session = SessionLocal()
    try:
        user = get_user_by_username(session, username)
        display_name = (user.display_name if user else "") or username
        email = (user.email if user else "") or ""

        # API keys for this tenant (read-only view)
        try:
            api_keys = list_api_keys_for_tenant(session, tenant_id)
        except Exception as e:
            logger.warning("Could not load API keys for profile: %s", e)
            api_keys = []

        key_rows = ""
        for k in api_keys[:10]:
            key_rows += f"""
            <tr>
                <td>{k.name}</td>
                <td><code>{k.key_prefix}...</code></td>
                <td>{k.created_at.strftime('%Y-%m-%d') if k.created_at else '-'}</td>
                <td>{k.last_used_at.strftime('%Y-%m-%d') if k.last_used_at else 'Never'}</td>
            </tr>"""
    finally:
        session.close()

    saved_msg = ""
    if request.query_params.get("saved"):
        saved_msg = '<div class="card" style="border-color:#238636;background:rgba(35,134,54,0.1);"><strong style="color:#3fb950">Profile updated successfully.</strong></div>'
    if request.query_params.get("pw_changed"):
        saved_msg = '<div class="card" style="border-color:#238636;background:rgba(35,134,54,0.1);"><strong style="color:#3fb950">Password changed successfully.</strong></div>'
    if request.query_params.get("pw_error"):
        saved_msg = '<div class="card" style="border-color:#da3633;background:rgba(218,54,51,0.1);"><strong style="color:#f85149">Current password is incorrect.</strong></div>'

    content = f"""
    {saved_msg}
    <div class="card">
        <h2 style="margin-top:0">Profile</h2>
        <p style="color:#8b949e">Manage your display name and password.</p>
    </div>

    <div class="card">
        <h3 style="margin-top:0">Account Info</h3>
        <form action="/profile/update-name" method="post">
            <div style="margin-bottom:15px">
                <label style="display:block; font-size:14px; margin-bottom:5px">Username</label>
                <input type="text" value="{username}" disabled
                    style="width:100%; padding:8px; background:#21262d; border:1px solid #30363d; border-radius:4px; color:#8b949e; box-sizing:border-box">
            </div>
            <div style="margin-bottom:15px">
                <label style="display:block; font-size:14px; margin-bottom:5px">Email</label>
                <input type="text" value="{email}" disabled
                    style="width:100%; padding:8px; background:#21262d; border:1px solid #30363d; border-radius:4px; color:#8b949e; box-sizing:border-box">
            </div>
            <div style="margin-bottom:15px">
                <label style="display:block; font-size:14px; margin-bottom:5px">Display Name</label>
                <input type="text" name="display_name" value="{display_name}"
                    style="width:100%; padding:8px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; box-sizing:border-box">
            </div>
            <button type="submit" class="btn btn-primary">Update Name</button>
        </form>
    </div>

    <div class="card">
        <h3 style="margin-top:0">Change Password</h3>
        <form action="/profile/change-password" method="post">
            <div style="margin-bottom:15px">
                <label style="display:block; font-size:14px; margin-bottom:5px">Current Password</label>
                <input type="password" name="current_password" required
                    style="width:100%; padding:8px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; box-sizing:border-box">
            </div>
            <div style="margin-bottom:15px">
                <label style="display:block; font-size:14px; margin-bottom:5px">New Password</label>
                <input type="password" name="new_password" required minlength="8"
                    style="width:100%; padding:8px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; box-sizing:border-box">
            </div>
            <div style="margin-bottom:15px">
                <label style="display:block; font-size:14px; margin-bottom:5px">Confirm New Password</label>
                <input type="password" name="confirm_password" required minlength="8"
                    style="width:100%; padding:8px; background:#0d1117; border:1px solid #30363d; border-radius:4px; color:#c9d1d9; box-sizing:border-box">
            </div>
            <button type="submit" class="btn btn-primary">Change Password</button>
        </form>
    </div>

    <div class="card">
        <h3 style="margin-top:0">API Keys (read-only)</h3>
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Prefix</th>
                    <th>Created</th>
                    <th>Last Used</th>
                </tr>
            </thead>
            <tbody>
                {key_rows if key_rows else '<tr><td colspan="4" style="text-align:center;color:#8b949e">No API keys</td></tr>'}
            </tbody>
        </table>
        <a href="/dashboard/api-keys" class="btn" style="margin-top:15px">Manage API Keys</a>
    </div>
    """
    return HTMLResponse(content=get_base_html("Profile", content, "Profile", username))


@router.post("/profile/update-name")
async def update_display_name(request: Request):
    from src.api.auth import verify_session_token
    from src.db.user_repo import get_user_by_username, update_display_name as _update_name

    token = request.cookies.get("session_token")
    username = verify_session_token(token)
    if not username:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    form = await request.form()
    new_name = (form.get("display_name") or "").strip()[:200]

    if new_name:
        session = SessionLocal()
        try:
            user = get_user_by_username(session, username)
            if user:
                _update_name(session, user, new_name)
        except Exception as e:
            logger.error("update_display_name failed for %s: %s", username, e)
        finally:
            session.close()

    return RedirectResponse(url="/dashboard/profile?saved=1", status_code=303)


@router.post("/profile/change-password")
async def change_password(request: Request):
    from src.api.auth import verify_session_token, check_password, hash_password
    from src.db.user_repo import get_user_by_username, update_password

    token = request.cookies.get("session_token")
    username = verify_session_token(token)
    if not username:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    form = await request.form()
    current_pw = form.get("current_password", "")
    new_pw = form.get("new_password", "")
    confirm_pw = form.get("confirm_password", "")

    if new_pw != confirm_pw or len(new_pw) < 8:
        return RedirectResponse(url="/dashboard/profile?pw_error=1", status_code=303)

    session = SessionLocal()
    try:
        user = get_user_by_username(session, username)
        if not user or not check_password(current_pw, user.password_hash):
            return RedirectResponse(url="/dashboard/profile?pw_error=1", status_code=303)
        update_password(session, user, hash_password(new_pw))
    except Exception as e:
        logger.error("change_password failed for %s: %s", username, e)
        return RedirectResponse(url="/dashboard/profile?pw_error=1", status_code=303)
    finally:
        session.close()

    return RedirectResponse(url="/dashboard/profile?pw_changed=1", status_code=303)


# ---------------------------------------------------------------------------
# Registration (B3)
# ---------------------------------------------------------------------------

_REGISTER_CSS = """
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
           background:#0d1117; color:#c9d1d9; display:flex; align-items:center; justify-content:center;
           height:100vh; margin:0; }
    .card { background:#161b22; border:1px solid #30363d; border-radius:6px; padding:40px;
            width:100%; max-width:420px; box-shadow:0 8px 24px rgba(0,0,0,0.5); }
    h1 { text-align:center; margin-bottom:30px; font-size:24px; }
    .form-group { margin-bottom:16px; }
    label { display:block; margin-bottom:6px; font-size:14px; color:#8b949e; }
    input { width:100%; padding:10px; background:#0d1117; border:1px solid #30363d;
            border-radius:6px; color:#c9d1d9; box-sizing:border-box; }
    button { width:100%; padding:12px; background:#238636; color:white; border:none;
             border-radius:6px; font-weight:bold; cursor:pointer; margin-top:10px; }
    button:hover { background:#2ea043; }
    .link-row { text-align:center; margin-top:16px; font-size:14px; color:#8b949e; }
    .link-row a { color:#58a6ff; text-decoration:none; }
    .error { color:#f85149; text-align:center; margin-bottom:10px; font-size:14px; }
"""


@public_router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    error = request.query_params.get("error", "")
    error_html = f'<div class="error">{error}</div>' if error else ""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><base href="http://REDACTED_IP:8001/"><title>DCSP — Create Account</title>
<style>{_REGISTER_CSS}</style></head>
<body>
<div class="card">
    <h1>Create Account</h1>
    {error_html}
    <form action="/auth/register" method="post">
        <div class="form-group">
            <label>Username</label>
            <input type="text" name="username" required autocomplete="username">
        </div>
        <div class="form-group">
            <label>Email</label>
            <input type="email" name="email" required autocomplete="email">
        </div>
        <div class="form-group">
            <label>Password</label>
            <input type="password" name="password" required minlength="8" autocomplete="new-password">
        </div>
        <div class="form-group">
            <label>Invite Code (optional)</label>
            <input type="text" name="invite_code" placeholder="Leave blank for free tier">
        </div>
        <button type="submit">Create Account</button>
    </form>
    <div class="link-row">Already have an account? <a href="/login">Sign in</a></div>
</div>
</body></html>"""
    return HTMLResponse(content=html)


@router.post("/auth/register")
async def register_user(request: Request):
    from src.api.auth import hash_password, create_session_token
    from src.db.user_repo import get_user_by_username, get_user_by_email, create_user
    from src.db.tenant_repo import create_tenant

    form = await request.form()
    username = (form.get("username") or "").strip().lower()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""

    if not username or not email or len(password) < 8:
        return RedirectResponse(
            url="/register?error=Username%2C+email+and+password+(8%2B+chars)+required",
            status_code=303,
        )

    session = SessionLocal()
    try:
        if get_user_by_username(session, username):
            return RedirectResponse(url="/register?error=Username+already+taken", status_code=303)
        if get_user_by_email(session, email):
            return RedirectResponse(url="/register?error=Email+already+registered", status_code=303)

        # Create a new tenant for this user
        new_tenant = create_tenant(session, name=f"{username}'s workspace", plan="free")
        new_hash = hash_password(password)
        user = create_user(
            session,
            username=username,
            email=email,
            password_hash=new_hash,
            tenant_id=new_tenant.id,
            role="admin",
        )
        logger.info("New user registered: %s (tenant %s)", username, new_tenant.id)
    except Exception as e:
        logger.error("Registration failed for %s: %s", username, e)
        return RedirectResponse(url="/register?error=Registration+failed+%E2%80%94+try+again", status_code=303)
    finally:
        session.close()

    token = create_session_token(username, new_tenant.id)
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(key="session_token", value=token, httponly=True, samesite="strict")
    response.set_cookie(key="ws_token", value=token, httponly=False, samesite="strict")
    return response


# ---------------------------------------------------------------------------
# Forgot / reset password (I3)
# ---------------------------------------------------------------------------

_SIMPLE_CSS = _REGISTER_CSS  # reuse same styles


@public_router.get("/auth/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    sent = request.query_params.get("sent")
    msg = ""
    if sent:
        msg = '<div style="color:#3fb950;text-align:center;margin-bottom:10px">Reset link sent — check your email (or server logs in dev).</div>'
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><base href="http://REDACTED_IP:8001/"><title>DCSP — Forgot Password</title>
<style>{_SIMPLE_CSS}</style></head>
<body>
<div class="card">
    <h1>Forgot Password</h1>
    {msg}
    <form action="/auth/forgot-password" method="post">
        <div class="form-group">
            <label>Email or Username</label>
            <input type="text" name="identifier" required>
        </div>
        <button type="submit">Send Reset Link</button>
    </form>
    <div class="link-row"><a href="/login">Back to login</a></div>
</div>
</body></html>"""
    return HTMLResponse(content=html)


@public_router.post("/auth/forgot-password")
async def forgot_password_post(request: Request):
    from src.api.auth import create_reset_token, send_reset_email
    from src.db.user_repo import get_user_by_username, get_user_by_email

    form = await request.form()
    identifier = (form.get("identifier") or "").strip()

    session = SessionLocal()
    try:
        user = get_user_by_username(session, identifier) or get_user_by_email(session, identifier)
    except Exception as e:
        logger.error("forgot_password DB lookup failed: %s", e)
        user = None
    finally:
        session.close()

    if user:
        token = create_reset_token(user.username)
        base = str(request.base_url).rstrip("/")
        reset_url = f"{base}/auth/reset-password/{token}"
        send_reset_email(user.username, user.email, reset_url)

    # Always redirect (don't reveal whether the user exists)
    return RedirectResponse(url="/auth/forgot-password?sent=1", status_code=303)


@public_router.get("/auth/reset-password/{reset_token}", response_class=HTMLResponse)
async def reset_password_page(reset_token: str, request: Request):
    from src.api.auth import verify_reset_token

    valid = verify_reset_token(reset_token)
    if not valid:
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><base href="http://REDACTED_IP:8001/"><title>DCSP — Invalid Link</title>
<style>{_SIMPLE_CSS}</style></head>
<body>
<div class="card">
    <h1>Invalid Link</h1>
    <p style="text-align:center;color:#8b949e">This reset link has expired or is invalid.</p>
    <div class="link-row"><a href="/auth/forgot-password">Request a new link</a></div>
</div></body></html>"""
        return HTMLResponse(content=html, status_code=400)

    error = request.query_params.get("error", "")
    error_html = f'<div class="error">{error}</div>' if error else ""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><base href="http://REDACTED_IP:8001/"><title>DCSP — Reset Password</title>
<style>{_SIMPLE_CSS}</style></head>
<body>
<div class="card">
    <h1>Reset Password</h1>
    {error_html}
    <form action="/auth/reset-password/{reset_token}" method="post">
        <div class="form-group">
            <label>New Password (min 8 characters)</label>
            <input type="password" name="new_password" required minlength="8" autocomplete="new-password">
        </div>
        <div class="form-group">
            <label>Confirm New Password</label>
            <input type="password" name="confirm_password" required minlength="8" autocomplete="new-password">
        </div>
        <button type="submit">Set New Password</button>
    </form>
</div>
</body></html>"""
    return HTMLResponse(content=html)


@public_router.post("/auth/reset-password/{reset_token}")
async def reset_password_post(reset_token: str, request: Request):
    from src.api.auth import consume_reset_token, hash_password
    from src.db.user_repo import get_user_by_username, update_password

    form = await request.form()
    new_pw = form.get("new_password") or ""
    confirm_pw = form.get("confirm_password") or ""

    if new_pw != confirm_pw or len(new_pw) < 8:
        return RedirectResponse(
            url=f"/auth/reset-password/{reset_token}?error=Passwords+must+match+and+be+at+least+8+characters",
            status_code=303,
        )

    username = consume_reset_token(reset_token)
    if not username:
        return RedirectResponse(url="/auth/forgot-password?sent=1", status_code=303)

    session = SessionLocal()
    try:
        user = get_user_by_username(session, username)
        if user:
            update_password(session, user, hash_password(new_pw))
            logger.info("Password reset completed for user %s", username)
    except Exception as e:
        logger.error("reset_password_post DB update failed for %s: %s", username, e)
    finally:
        session.close()

    return RedirectResponse(url="/login?reset=1", status_code=303)
