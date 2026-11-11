"""
AetherOS — Auth Router
Authentication and API key management.
Full inline implementations migrated from api.py (was previously stubs).
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user
from aether_os.core.audit.ledger import get_ledger
from aether_os.core.db import get_session_factory
from aether_os.core.guardian.password_shield import check_password_safety
from aether_os.core.models import Organisation, User
from aether_os.core.notifications.email import get_email_notifier
from aether_os.core.pipeline_state import get_redis
from aether_os.core.rate_limiter import get_client_ip, get_rate_limiter
from aether_os.gateway.auth_refresh import issue_token_pair, revoke_session
from aether_os.gateway.auth import get_password_hash, create_access_token
from aether_os.gateway.auth import verify_password, create_access_token
from sqlalchemy import select
import os as _os
import secrets
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
_CURRENT_TOS_VERSION = "1.0"
_CURRENT_DPA_VERSION = "1.0"
# ── Pydantic models ────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str
class RegisterRequest(BaseModel):
    model_config = {"extra": "forbid"}  # B1: reject any unlisted field (plan, role, is_admin, etc.)
    email: str
    password: str
    name: Optional[str] = None
    org_name: Optional[str] = None
    terms_accepted: bool = False    # D4: GDPR consent — must be True (covers ToS + EULA)
    dpa_accepted: bool = False      # T4-01: GDPR Article 28 Data Processing Agreement
class LoginResponse(BaseModel):
    access_token: str = ""
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    org_slug: str = ""
    org_id: str = ""
    plan: str = ""
    mfa_required: bool = False
    mfa_token: Optional[str] = None
def _auth():
    return Depends(get_current_user)
# ── Routes ────────────────────────────────────────────────────────────────────
@router.post("/register", response_model=LoginResponse)
async def register(req: RegisterRequest, request: Request) -> LoginResponse:
    """Register a new organisation and owner user."""
    # Rate-limit registrations by IP to prevent spam org creation
    client_ip = get_client_ip(request)
    rl = get_rate_limiter()
    await rl.record_registration_attempt(client_ip)
    if not await rl.check_registration_attempts(client_ip):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Please try again later.")
    # D4: GDPR consent + T4-01: DPA acceptance gate
    if not req.terms_accepted or not req.dpa_accepted:
        raise HTTPException(status_code=422, detail="terms_and_dpa_required")
    # Password safety: complexity + HIBP breach check
    try:
        _pw_safe, _pw_reason = await check_password_safety(req.password)
        if not _pw_safe:
            raise HTTPException(status_code=422, detail=_pw_reason)
    except HTTPException:
        raise
    except Exception as _pw_exc:
        # Fail open — never block registration due to shield errors
        logger.warning("Password shield check failed: %s", _pw_exc)
    session_factory = get_session_factory()
    async with session_factory() as session:
        # Check if email exists
        stmt = select(User).where(User.email == req.email)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")
        # Create org — plan is always "trial" regardless of request body (B1)
        _org_name = req.org_name or req.email.split("@")[0]
        _base_slug = re.sub(r"[^a-z0-9-]", "-", _org_name.lower().strip()).strip("-") or "org"
        # Guarantee slug uniqueness by appending a random 6-char suffix
        slug = f"{_base_slug}-{uuid.uuid4().hex[:6]}"
        org = Organisation(
            id=str(uuid.uuid4()),
            name=_org_name,
            slug=slug,
            plan="trial",  # B1: hardcoded — never from request
        )
        session.add(org)
        # Create owner user — role is always "owner" regardless of request body (B1)
        _consent_now = datetime.now(timezone.utc).replace(tzinfo=None)
        _consent_meta = json.dumps({
            "tos_version": _CURRENT_TOS_VERSION,
            "dpa_version": _CURRENT_DPA_VERSION,
            "consent_at": _consent_now.isoformat() + "Z",
        })
        user = User(
            id=str(uuid.uuid4()),
            org_id=org.id,
            email=req.email,
            password_hash=get_password_hash(req.password),
            role="owner",  # B1: hardcoded — never from request
            consent_at=_consent_now,  # D4: GDPR consent timestamp
            user_preferences=_consent_meta,  # T4-01: stores ToS+DPA version accepted
        )
        session.add(user)
        await session.commit()
        # Email verification token
        verify_token = secrets.token_urlsafe(32)
        try:
            r = await get_redis()
            if r:
                # Store verification token in Redis (24 hours expiry)
                await r.set(f"email_verify:{verify_token}", user.id, ex=86400)
        except Exception as exc:
            logger.debug("Failed to store email verification token in Redis for user %s: %s", user.id, exc)
        # Send verification email with absolute URL
        _base_url = _os.environ.get("PUBLIC_BASE_URL", str(request.base_url).rstrip("/"))
        notifier = get_email_notifier()
        subject = "Welcome to AetherOS — verify your email"
        body = (
            f"Welcome to AetherOS, {req.name or _org_name}!\n\n"
            f"Your organisation '{_org_name}' is ready. "
            f"Please verify your email by clicking the link below:\n\n"
            f"{_base_url}/auth/verify-email?token={verify_token}\n\n"
            f"This link expires in 24 hours.\n\n"
            f"If you didn't create this account, you can safely ignore this email."
        )
        await notifier.send(user.email, subject, body)
        # Audit: user_registered
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=org.id,
            user_id=user.id,
            action="user_registered",
            resource_type="user",
            resource_id=user.id,
            ip_address=client_ip,
            user_agent=request.headers.get("User-Agent", "-")
        ))
        _reg_claims = {
            "sub": user.email,
            "user_id": user.id,
            "org_id": org.id,
            "org_slug": org.slug,
            "role": user.role,
            "plan": org.plan,
        }
        token, refresh = issue_token_pair(_reg_claims)
        return LoginResponse(
            access_token=token,
            refresh_token=refresh,
            org_slug=org.slug,
            org_id=org.id,
            plan=org.plan,
        )
@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request) -> LoginResponse:
    """Authenticate and return a JWT token."""
    # Rate-limit login attempts by IP — prevents brute force
    client_ip = get_client_ip(request)
    rl = get_rate_limiter()
    await rl.record_login_attempt(client_ip)
    if not await rl.check_login_attempts(client_ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Please wait 15 minutes before trying again.")
    user_agent = request.headers.get("User-Agent", "-")
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(User, Organisation).join(Organisation).where(User.email == req.email)
        result = await session.execute(stmt)
        row = result.fetchone()
        if not row:
            asyncio.create_task(get_ledger().async_log_audit_event(
                org_id="-", user_id="-", action="login_failed",
                metadata={"email": req.email, "reason": "user_not_found"},
                ip_address=client_ip, user_agent=user_agent
            ))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        loop = asyncio.get_running_loop()
        pw_ok = await loop.run_in_executor(None, verify_password, req.password, row[0].password_hash)
        if not pw_ok:
            asyncio.create_task(get_ledger().async_log_audit_event(
                org_id=row[1].id, user_id=row[0].id, action="login_failed",
                metadata={"email": req.email, "reason": "invalid_password"},
                ip_address=client_ip, user_agent=user_agent
            ))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        user, org = row
        if not user.is_active:
            asyncio.create_task(get_ledger().async_log_audit_event(
                org_id=org.id, user_id=user.id, action="login_failed",
                metadata={"email": req.email, "reason": "account_disabled"},
                ip_address=client_ip, user_agent=user_agent
            ))
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
        # Audit: login_success
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=org.id, user_id=user.id, action="login_success",
            ip_address=client_ip, user_agent=user_agent
        ))
        if user.mfa_enabled:
            # Issue a 5-minute partial token — client must complete MFA via /auth/mfa/confirm
            # The mfa_pending claim prevents this token from being used for real API calls
            mfa_token = create_access_token(
                {"mfa_pending": True, "user_id": user.id},
                expires_hours=1,  # 1hr ceiling; mfa_pending claim is the real gate
            )
            return LoginResponse(mfa_required=True, mfa_token=mfa_token)
        _token_claims = {
            "sub": user.email,
            "user_id": user.id,
            "org_id": org.id,
            "org_slug": org.slug,
            "role": user.role,
            "plan": org.plan,
        }
        token, refresh = issue_token_pair(_token_claims)
        return LoginResponse(
            access_token=token,
            refresh_token=refresh,
            org_slug=org.slug,
            org_id=org.id,
            plan=org.plan,
        )
@router.post("/logout")
async def logout(request: Request, user: Dict[str, Any] = _auth()) -> Dict[str, str]:
    """Blacklist this access token and revoke the refresh-token family issued with it."""
    asyncio.create_task(get_ledger().async_log_audit_event(
        org_id=user.get("org_id", "-"),
        user_id=user.get("user_id", "-"),
        action="logout",
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent", "-")
    ))
    # Raises 503 if the revocation could not be stored: "Logged out" must be true.
    await revoke_session(user)
    return {"message": "Logged out"}
# ── Token refresh lives in auth_refresh_router.py (split to stay under 400 lines) ─
# ── Email verification and password routes live in auth_password_router.py ─────
# ── API keys, MFA status, and org-switcher routes live in auth_keys_router.py ─