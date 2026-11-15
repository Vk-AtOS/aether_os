"""
AetherOS — OAuth2 Social Login (Google + GitHub)

Routes:
  GET /auth/oauth/google           → redirect to Google authorization
  GET /auth/oauth/google/callback  → exchange code, issue JWT, redirect frontend
  GET /auth/oauth/github           → redirect to GitHub authorization
  GET /auth/oauth/github/callback  → exchange code, issue JWT, redirect frontend

Environment variables:
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
  GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET
  OAUTH_REDIRECT_BASE   — public base URL (e.g. https://app.aetheros.io)
  FRONTEND_URL          — dashboard URL (defaults to OAUTH_REDIRECT_BASE)
"""
from __future__ import annotations

import logging
import os
import secrets
import urllib.parse
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from aether_os.gateway.auth_refresh import oauth_state_pop, oauth_state_set

logger = logging.getLogger(__name__)
oauth_router = APIRouter(prefix="/auth/oauth", tags=["oauth"])

# ── CSRF state ────────────────────────────────────────────────────────────────
# Stored in Redis (gateway/auth_refresh.py): the callback can land on any worker.

async def _new_state(provider: str) -> str:
    state = secrets.token_urlsafe(32)
    await oauth_state_set(state, provider)
    return state


_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

_GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"
_GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


def _base_url() -> str:
    return os.environ.get("OAUTH_REDIRECT_BASE", "http://localhost:8000").rstrip("/")


def _frontend_url() -> str:
    return os.environ.get("FRONTEND_URL", _base_url()).rstrip("/")


def _redirect_with_token(token: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"{_frontend_url()}/auth/callback?token={urllib.parse.quote(token)}",
        status_code=302,
    )


def _signin_redirect(user, org) -> RedirectResponse:
    """Token redirect, or a pending-MFA token when the account has MFA enabled."""
    if getattr(user, "mfa_enabled", False):
        from aether_os.gateway.auth import create_access_token
        mfa_token = create_access_token({"mfa_pending": True, "user_id": user.id}, expires_hours=1)
        return RedirectResponse(
            url=f"{_frontend_url()}/auth/callback?mfa_required=1&mfa_token={urllib.parse.quote(mfa_token)}",
            status_code=302,
        )
    return _redirect_with_token(_make_jwt(user, org))


def _redirect_with_error(message: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"{_frontend_url()}/login?error={urllib.parse.quote(message)}",
        status_code=302,
    )


async def _upsert_oauth_user(email: str):
    """Find or create User + Organisation for the given OAuth email. Returns (user, org)."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation, User
    from aether_os.gateway.auth import get_password_hash
    from sqlalchemy import select

    sf = get_session_factory()
    async with sf() as session:
        row = (
            await session.execute(
                select(User, Organisation)
                .join(Organisation)
                .where(User.email == email)
            )
        ).fetchone()
        if row:
            user, org = row
            if not user.email_verified:
                # Never auto-link an unverified local account: whoever pre-registered
                # it may hold refresh tokens, API keys, MFA secrets or invites. The
                # owner confirms the address via the verification email first.
                raise HTTPException(status_code=403, detail="Verify your email address before signing in with a provider")
        else:
            handle = email.split("@")[0].lower().replace(".", "-")
            slug = f"{handle}-{secrets.token_hex(3)}"
            org = Organisation(
                id=str(uuid.uuid4()),
                name=email,
                slug=slug,
                plan="trial",
            )
            session.add(org)
            user = User(
                id=str(uuid.uuid4()),
                org_id=org.id,
                email=email,
                password_hash=get_password_hash(secrets.token_urlsafe(32)),
                role="owner",
                email_verified=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            await session.refresh(org)
        return user, org


def _make_jwt(user, org) -> str:
    from aether_os.gateway.auth import create_access_token
    return create_access_token({
        "sub": user.email,
        "user_id": user.id,
        "org_id": org.id,
        "org_slug": org.slug,
        "role": user.role,
        "plan": org.plan,
    })


# ── Google ────────────────────────────────────────────────────────────────────

@oauth_router.get("/google", include_in_schema=True)
async def google_login() -> RedirectResponse:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")

    state = await _new_state("google")
    callback_url = f"{_base_url()}/api/auth/oauth/google/callback"
    params = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return RedirectResponse(url=_GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params))


@oauth_router.get("/google/callback", include_in_schema=False)
async def google_callback(
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None,
) -> RedirectResponse:
    if error or not code:
        return _redirect_with_error(error or "Google sign-in was cancelled")
    if not state or not await oauth_state_pop(state, "google"):
        logger.warning("Google OAuth callback: invalid or missing CSRF state")
        return _redirect_with_error("OAuth state mismatch — please try signing in again")

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return _redirect_with_error("Google OAuth is not configured")

    callback_url = f"{_base_url()}/api/auth/oauth/google/callback"
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            tok = await http.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": callback_url,
                    "grant_type": "authorization_code",
                },
            )
            tok.raise_for_status()
            access_token = tok.json()["access_token"]

            info_resp = await http.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            info_resp.raise_for_status()
            info = info_resp.json()

        email = info.get("email")
        if not email:
            return _redirect_with_error("Google did not return an email address")
        # SEC: default False — block if Google omits email_verified (fail-safe)
        if not info.get("email_verified", False):
            return _redirect_with_error("Google account email is not verified")

        user, org = await _upsert_oauth_user(email=email)
        return _signin_redirect(user, org)
    except HTTPException as exc:
        return _redirect_with_error(str(exc.detail))
    except Exception:
        # SEC: Do not expose internal exception details in redirect URL
        logger.exception("Google OAuth callback failed")
        return _redirect_with_error("Google sign-in failed. Please try again.")


# ── GitHub ────────────────────────────────────────────────────────────────────

@oauth_router.get("/github", include_in_schema=True)
async def github_login() -> RedirectResponse:
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured")

    state = await _new_state("github")
    callback_url = f"{_base_url()}/api/auth/oauth/github/callback"
    params = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "scope": "user:email",
        "state": state,
    }
    return RedirectResponse(url=_GITHUB_AUTH_URL + "?" + urllib.parse.urlencode(params))


@oauth_router.get("/github/callback", include_in_schema=False)
async def github_callback(
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None,
) -> RedirectResponse:
    if error or not code:
        return _redirect_with_error(error or "GitHub sign-in was cancelled")
    if not state or not await oauth_state_pop(state, "github"):
        logger.warning("GitHub OAuth callback: invalid or missing CSRF state")
        return _redirect_with_error("OAuth state mismatch — please try signing in again")

    client_id = os.environ.get("GITHUB_CLIENT_ID")
    client_secret = os.environ.get("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        return _redirect_with_error("GitHub OAuth is not configured")

    callback_url = f"{_base_url()}/api/auth/oauth/github/callback"
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            tok = await http.post(
                _GITHUB_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": callback_url,
                },
                headers={"Accept": "application/json"},
            )
            tok.raise_for_status()
            access_token = tok.json().get("access_token")
            if not access_token:
                return _redirect_with_error("GitHub token exchange failed")

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json",
            }

            user_resp = await http.get(_GITHUB_USER_URL, headers=headers)
            user_resp.raise_for_status()
            gh_user = user_resp.json()

            # GitHub may not expose primary email on the user object — fetch separately
            email = gh_user.get("email")
            if not email:
                emails_resp = await http.get(_GITHUB_EMAILS_URL, headers=headers)
                emails_resp.raise_for_status()
                for e in emails_resp.json():
                    if e.get("primary") and e.get("verified"):
                        email = e["email"]
                        break

        if not email:
            return _redirect_with_error("GitHub did not return a verified email address")

        user, org = await _upsert_oauth_user(email=email)
        return _signin_redirect(user, org)
    except HTTPException as exc:
        return _redirect_with_error(str(exc.detail))
    except Exception:
        # SEC: Do not expose internal exception details in redirect URL
        logger.exception("GitHub OAuth callback failed")
        return _redirect_with_error("GitHub sign-in failed. Please try again.")
