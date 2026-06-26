"""
Authentication router for DCSP.

GET  /register               — registration page (SSR)
GET  /auth/forgot-password   — forgot-password page (SSR)
POST /auth/login      — form-based login (SSR flow, sets cookie + redirects)
POST /auth/login-api  — JSON login for the React SPA (returns token info)
POST /auth/signup     — email-based account creation for the React SPA
POST /auth/logout     — invalidate session
GET  /auth/me         — return current user info
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from src.api.auth import (
    verify_credentials,
    create_session_token,
    verify_session_token,
    invalidate_session,
    hash_password,
)
from src.database import SessionLocal
from src.db.audit_repo import save_audit_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# GET /register — public registration page
# Registered on the bare router (no prefix) so the URL is /register, not /auth/register.
# ---------------------------------------------------------------------------

_REGISTER_ROUTER = APIRouter()


@_REGISTER_ROUTER.get("/register", response_class=HTMLResponse)
async def get_register_page():
    """Serve the account registration page."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <base href="http://139.59.87.218:8001/">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Create Account - DCSP</title>
    <style>
        :root { --bg-color: #0d1117; --card-bg: #161b22; --text-color: #c9d1d9;
                --accent-color: #58a6ff; --success-color: #238636;
                --error-color: #da3633; --border-color: #30363d; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
               background-color: var(--bg-color); color: var(--text-color);
               display: flex; align-items: center; justify-content: center;
               min-height: 100vh; margin: 0; }
        .card { background-color: var(--card-bg); border: 1px solid var(--border-color);
                border-radius: 6px; padding: 40px; width: 100%; max-width: 420px;
                box-shadow: 0 8px 24px rgba(0,0,0,0.5); }
        h1 { text-align: center; margin-bottom: 8px; font-size: 24px; }
        .subtitle { text-align: center; color: #8b949e; font-size: 14px; margin-bottom: 28px; }
        .form-group { margin-bottom: 18px; }
        label { display: block; margin-bottom: 6px; font-size: 14px; color: #8b949e; }
        input { width: 100%; padding: 10px; background-color: var(--bg-color);
                border: 1px solid var(--border-color); border-radius: 6px;
                color: var(--text-color); box-sizing: border-box; font-size: 14px; }
        input:focus { outline: none; border-color: var(--accent-color); }
        button { width: 100%; padding: 12px; background-color: var(--success-color);
                 color: white; border: none; border-radius: 6px; font-weight: bold;
                 cursor: pointer; margin-top: 6px; font-size: 15px; }
        button:hover { background-color: #2ea043; }
        .footer-links { margin-top: 20px; text-align: center; font-size: 14px; color: #8b949e; }
        .footer-links a { color: var(--accent-color); text-decoration: none; }
        #msg { margin-bottom: 14px; padding: 10px; border-radius: 4px;
               font-size: 13px; display: none; }
        #msg.error { background: rgba(218,54,51,0.15); color: #f85149;
                     border: 1px solid rgba(218,54,51,0.4); }
        #msg.success { background: rgba(35,134,54,0.15); color: #3fb950;
                       border: 1px solid rgba(35,134,54,0.4); }
    </style>
</head>
<body>
    <div class="card">
        <h1>Create your DCSP account</h1>
        <p class="subtitle">Start repairing CI failures automatically</p>
        <div id="msg"></div>
        <form id="reg-form">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required
                       autocomplete="username" placeholder="e.g. johndoe">
            </div>
            <div class="form-group">
                <label for="email">Email</label>
                <input type="email" id="email" name="email" required
                       autocomplete="email" placeholder="you@company.com">
            </div>
            <div class="form-group">
                <label for="password">Password <span style="color:#8b949e;font-size:12px">(min 8 chars)</span></label>
                <input type="password" id="password" name="password" required
                       autocomplete="new-password" minlength="8">
            </div>
            <button type="submit">Create account</button>
        </form>
        <div class="footer-links">
            Already have an account? <a href="/login">Sign in</a>
        </div>
    </div>
    <script>
    document.getElementById('reg-form').addEventListener('submit', async function(e) {
        e.preventDefault();
        const msg = document.getElementById('msg');
        msg.style.display = 'none';
        const body = {
            username: document.getElementById('username').value,
            email: document.getElementById('email').value,
            password: document.getElementById('password').value,
        };
        try {
            const res = await fetch('/auth/signup', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (res.ok) {
                window.location.href = '/dashboard';
            } else {
                msg.className = 'error';
                msg.textContent = data.detail || 'Registration failed. Please try again.';
                msg.style.display = 'block';
            }
        } catch (err) {
            msg.className = 'error';
            msg.textContent = 'Network error. Please try again.';
            msg.style.display = 'block';
        }
    });
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# GET /auth/forgot-password — public forgot-password page
# ---------------------------------------------------------------------------

@router.get("/forgot-password", response_class=HTMLResponse)
async def get_forgot_password_page():
    """Serve the forgot-password page."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <base href="http://139.59.87.218:8001/">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reset Password - DCSP</title>
    <style>
        :root { --bg-color: #0d1117; --card-bg: #161b22; --text-color: #c9d1d9;
                --accent-color: #58a6ff; --success-color: #238636;
                --error-color: #da3633; --border-color: #30363d; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
               background-color: var(--bg-color); color: var(--text-color);
               display: flex; align-items: center; justify-content: center;
               min-height: 100vh; margin: 0; }
        .card { background-color: var(--card-bg); border: 1px solid var(--border-color);
                border-radius: 6px; padding: 40px; width: 100%; max-width: 400px;
                box-shadow: 0 8px 24px rgba(0,0,0,0.5); }
        h1 { text-align: center; margin-bottom: 8px; font-size: 24px; }
        .subtitle { text-align: center; color: #8b949e; font-size: 14px; margin-bottom: 28px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 6px; font-size: 14px; color: #8b949e; }
        input { width: 100%; padding: 10px; background-color: var(--bg-color);
                border: 1px solid var(--border-color); border-radius: 6px;
                color: var(--text-color); box-sizing: border-box; font-size: 14px; }
        input:focus { outline: none; border-color: var(--accent-color); }
        button { width: 100%; padding: 12px; background-color: var(--success-color);
                 color: white; border: none; border-radius: 6px; font-weight: bold;
                 cursor: pointer; margin-top: 6px; font-size: 15px; }
        button:hover { background-color: #2ea043; }
        .footer-links { margin-top: 20px; text-align: center; font-size: 14px; color: #8b949e; }
        .footer-links a { color: var(--accent-color); text-decoration: none; }
        #msg { margin-bottom: 14px; padding: 10px; border-radius: 4px;
               font-size: 13px; display: none; }
        #msg.error { background: rgba(218,54,51,0.15); color: #f85149;
                     border: 1px solid rgba(218,54,51,0.4); }
        #msg.success { background: rgba(35,134,54,0.15); color: #3fb950;
                       border: 1px solid rgba(35,134,54,0.4); }
    </style>
</head>
<body>
    <div class="card">
        <h1>Reset your password</h1>
        <p class="subtitle">Enter your email and we'll send a reset link</p>
        <div id="msg"></div>
        <form id="forgot-form">
            <div class="form-group">
                <label for="email">Email address</label>
                <input type="email" id="email" name="email" required
                       autocomplete="email" placeholder="you@company.com">
            </div>
            <button type="submit">Send reset link</button>
        </form>
        <div class="footer-links">
            Remembered it? <a href="/login">Back to sign in</a>
        </div>
    </div>
    <script>
    document.getElementById('forgot-form').addEventListener('submit', async function(e) {
        e.preventDefault();
        const msg = document.getElementById('msg');
        msg.style.display = 'none';
        const email = document.getElementById('email').value;
        try {
            const res = await fetch('/auth/forgot-password', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({email}),
            });
            // Always show a generic success message to avoid email enumeration
            msg.className = 'success';
            msg.textContent = 'If that email is registered, a reset link has been sent.';
            msg.style.display = 'block';
            document.getElementById('forgot-form').reset();
        } catch (err) {
            msg.className = 'error';
            msg.textContent = 'Network error. Please try again.';
            msg.style.display = 'block';
        }
    });
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
):
    """Handle login form submission. Verifies bcrypt hash and creates a Redis-backed session."""
    session = SessionLocal()
    try:
        if verify_credentials(username, password):
            save_audit_log(session, "login_success", username, ip_address=request.client.host)

            # Retrieve tenant_id for the user so it can be stored in the session
            tenant_id: str | None = None
            try:
                from src.db.user_repo import get_user_by_username
                user = get_user_by_username(session, username)
                if user:
                    tenant_id = user.tenant_id
            except Exception as e:
                logger.warning("Could not fetch tenant_id for user %s at login: %s", username, e)

            token = create_session_token(username, tenant_id)
            # Primary session cookie — HttpOnly prevents JS access (XSS protection)
            resp = RedirectResponse(url="/dashboard", status_code=303)
            resp.set_cookie(key="session_token", value=token, httponly=True, samesite="strict")
            # ws_token carries the same value but is JS-readable for the WebSocket client.
            resp.set_cookie(key="ws_token", value=token, httponly=False, samesite="strict")
            return resp

        save_audit_log(
            session,
            "login_failure",
            username,
            details="Invalid credentials",
            ip_address=request.client.host,
        )
        return RedirectResponse(url="/login?error=1", status_code=303)
    finally:
        session.close()


@router.post("/logout")
async def logout(request: Request):
    """Invalidate the current session."""
    token = request.cookies.get("session_token")
    if token:
        invalidate_session(token)
    resp = JSONResponse({"success": True})
    resp.delete_cookie("session_token")
    resp.delete_cookie("ws_token")
    return resp


class LoginRequest(BaseModel):
    username: str
    password: str


class SignupRequest(BaseModel):
    username: str
    email: str
    password: str


@router.post("/login-api")
async def login_api(req: LoginRequest, request: Request):
    """JSON login endpoint for the React SPA. Returns session info, sets HttpOnly cookie."""
    session = SessionLocal()
    try:
        if not verify_credentials(req.username, req.password):
            save_audit_log(
                session, "login_failure", req.username,
                details="Invalid credentials",
                ip_address=request.client.host if request.client else "unknown",
            )
            raise HTTPException(status_code=401, detail="Invalid username or password")

        save_audit_log(
            session, "login_success", req.username,
            ip_address=request.client.host if request.client else "unknown",
        )

        tenant_id: str | None = None
        role = "user"
        try:
            from src.db.user_repo import get_user_by_username
            user = get_user_by_username(session, req.username)
            if user:
                tenant_id = user.tenant_id
                role = getattr(user, "role", "user") or "user"
        except Exception as e:
            logger.warning("Could not fetch user info at login: %s", e)

        token = create_session_token(req.username, tenant_id)
        resp = JSONResponse({
            "success": True,
            "username": req.username,
            "role": role,
            "tenant_id": tenant_id,
        })
        resp.set_cookie(key="session_token", value=token, httponly=True, samesite="lax")
        resp.set_cookie(key="ws_token",      value=token, httponly=False, samesite="lax")
        return resp
    finally:
        session.close()


@router.post("/signup")
async def signup(req: SignupRequest, request: Request):
    """Create a new user account. Used by the React SPA sign-up form."""
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not req.email or "@" not in req.email:
        raise HTTPException(status_code=400, detail="A valid email address is required")

    session = SessionLocal()
    try:
        from src.models import User
        from src.db.user_repo import get_user_by_username

        existing = get_user_by_username(session, req.username)
        if existing:
            raise HTTPException(status_code=409, detail="Username already taken")

        # Check email uniqueness
        try:
            existing_email = session.query(User).filter(User.email == req.email).first()
            if existing_email:
                raise HTTPException(status_code=409, detail="Email already registered")
        except HTTPException:
            raise
        except Exception:
            pass  # email column may not exist in older schema — allow signup

        pw_hash = hash_password(req.password)
        try:
            from src.db.user_repo import create_user
            create_user(
                session,
                username=req.username,
                email=req.email,
                password_hash=pw_hash,
                role="member",
            )
        except Exception as e:
            session.rollback()
            logger.error("Signup commit failed: %s", e)
            raise HTTPException(status_code=500, detail="Account creation failed. Try a different username.")

        save_audit_log(
            session, "signup_success", req.username,
            ip_address=request.client.host if request.client else "unknown",
        )

        token = create_session_token(req.username, None)
        resp = JSONResponse({
            "success": True,
            "username": req.username,
            "role": "user",
        })
        resp.set_cookie(key="session_token", value=token, httponly=True, samesite="lax")
        resp.set_cookie(key="ws_token",      value=token, httponly=False, samesite="lax")
        return resp
    finally:
        session.close()


@router.get("/me")
async def me(request: Request):
    """Return current user info. Used by the React SPA to check auth state."""
    token = request.cookies.get("session_token")
    username = verify_session_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = SessionLocal()
    try:
        role = "user"
        try:
            from src.db.user_repo import get_user_by_username
            user = get_user_by_username(session, username)
            if user:
                role = getattr(user, "role", "user") or "user"
        except Exception as e:
            logger.debug("Could not fetch role for %s: %s", username, e)
        return {"username": username, "role": role, "authenticated": True}
    finally:
        session.close()


async def get_current_user(request: Request) -> str:
    """Dependency: verify session token and return username, or redirect to login."""
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    username = verify_session_token(token)
    if not username:
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    return username


async def get_current_user_api(request: Request) -> str:
    """Dependency for JSON API endpoints — returns 401 (not 302) when unauthenticated."""
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = verify_session_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid session")
    return username
