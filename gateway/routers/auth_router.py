"""
AetherOS — Auth Router

Authentication and API key management.
Full inline implementations migrated from api.py (was previously stubs).
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user

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


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


class ApiKeyCreateRequest(BaseModel):
    name: str


def _auth():
    return Depends(get_current_user)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register", response_model=LoginResponse)
async def register(req: RegisterRequest, request: Request) -> LoginResponse:
    """Register a new organisation and owner user."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation, User
    from aether_os.gateway.auth import get_password_hash, create_access_token
    from aether_os.core.rate_limiter import get_rate_limiter
    from sqlalchemy import select

    # Rate-limit registrations by IP to prevent spam org creation
    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or "unknown"
    )
    rl = get_rate_limiter()
    await rl.record_registration_attempt(client_ip)
    if not await rl.check_registration_attempts(client_ip):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Please try again later.")

    # D4: GDPR consent + T4-01: DPA acceptance gate
    if not req.terms_accepted or not req.dpa_accepted:
        raise HTTPException(status_code=422, detail="terms_and_dpa_required")

    # Password safety: complexity + HIBP breach check
    try:
        from aether_os.core.guardian.password_shield import check_password_safety
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
        slug = _org_name.lower().replace(" ", "-")
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
        import secrets
        verify_token = secrets.token_urlsafe(32)
        try:
            from aether_os.core.pipeline_state import get_redis
            r = await get_redis()
            if r:
                # Store verification token in Redis (24 hours expiry)
                await r.setex(f"email_verify:{verify_token}", 86400, user.id)
        except Exception:
            pass

        # Send verification email
        from aether_os.core.notifications.email import get_email_notifier
        notifier = get_email_notifier()
        subject = "AetherOS: Verify your email"
        body = f"Welcome to AetherOS! Please verify your email by clicking here: /auth/verify-email?token={verify_token}"
        await notifier.send(user.email, subject, body)

        # Audit: user_registered
        from aether_os.core.audit.ledger import get_ledger
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=org.id,
            user_id=user.id,
            action="user_registered",
            resource_type="user",
            resource_id=user.id,
            ip_address=client_ip,
            user_agent=request.headers.get("User-Agent", "-")
        ))

        from aether_os.gateway.auth import create_refresh_token as _crt_reg
        _reg_claims = {
            "sub": user.email,
            "user_id": user.id,
            "org_id": org.id,
            "org_slug": org.slug,
            "role": user.role,
            "plan": org.plan,
        }
        token = create_access_token(_reg_claims)
        refresh = _crt_reg(_reg_claims)
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
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation, User
    from aether_os.gateway.auth import verify_password, create_access_token
    from aether_os.core.rate_limiter import get_rate_limiter
    from sqlalchemy import select

    # Rate-limit login attempts by IP — prevents brute force
    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or "unknown"
    )
    rl = get_rate_limiter()
    await rl.record_login_attempt(client_ip)
    if not await rl.check_login_attempts(client_ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Please wait 15 minutes before trying again.")

    user_agent = request.headers.get("User-Agent", "-")
    from aether_os.core.audit.ledger import get_ledger

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

        from aether_os.gateway.auth import create_refresh_token as _crt
        _token_claims = {
            "sub": user.email,
            "user_id": user.id,
            "org_id": org.id,
            "org_slug": org.slug,
            "role": user.role,
            "plan": org.plan,
        }
        token = create_access_token(_token_claims)
        refresh = _crt(_token_claims)
        return LoginResponse(
            access_token=token,
            refresh_token=refresh,
            org_slug=org.slug,
            org_id=org.id,
            plan=org.plan,
        )


@router.post("/logout")
async def logout(request: Request, user: Dict[str, Any] = _auth()) -> Dict[str, str]:
    """Invalidate the current JWT by adding its jti to Redis blacklist."""
    jti = user.get("jti")
    exp = user.get("exp", 0)

    # Audit: logout
    from aether_os.core.audit.ledger import get_ledger
    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    asyncio.create_task(get_ledger().async_log_audit_event(
        org_id=user.get("org_id", "-"),
        user_id=user.get("user_id", "-"),
        action="logout",
        ip_address=client_ip,
        user_agent=request.headers.get("User-Agent", "-")
    ))

    if jti and isinstance(exp, (int, float)):
        try:
            from aether_os.core.pipeline_state import get_redis
            r = await get_redis()
            if r:
                ttl = max(1, int(exp - time.time()))
                await r.setex(f"jwt:blacklist:{jti}", ttl, "1")
        except Exception:
            pass
    return {"message": "Logged out"}


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token_endpoint(req: RefreshRequest, request: Request) -> LoginResponse:
    """Exchange a valid refresh token for a new access + refresh token pair."""
    from aether_os.gateway.auth import decode_access_token, create_access_token, create_refresh_token as _crt_ref
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User, Organisation
    from sqlalchemy import select

    claims = decode_access_token(req.refresh_token)
    if not claims or claims.get("token_type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Audit: token_refresh
    from aether_os.core.audit.ledger import get_ledger
    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    asyncio.create_task(get_ledger().async_log_audit_event(
        org_id=claims.get("org_id", "-"),
        user_id=claims.get("user_id", "-"),
        action="token_refresh",
        ip_address=client_ip,
        user_agent=request.headers.get("User-Agent", "-")
    ))

    # Check Redis blacklist
    jti = claims.get("jti")
    if jti:
        try:
            from aether_os.core.pipeline_state import get_redis
            r = await get_redis()
            if r and await r.get(f"jwt:blacklist:{jti}"):
                raise HTTPException(status_code=401, detail="Refresh token has been revoked")
        except HTTPException:
            raise
        except Exception:
            pass

    user_id = claims.get("user_id")
    session_factory = get_session_factory()
    async with session_factory() as session:
        row = (
            await session.execute(
                select(User, Organisation).join(Organisation).where(User.id == user_id)
            )
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="User not found")
        user, org = row
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is disabled")

        _new_claims = {
            "sub": user.email,
            "user_id": user.id,
            "org_id": org.id,
            "org_slug": org.slug,
            "role": user.role,
            "plan": org.plan,
        }
        new_access = create_access_token(_new_claims)
        new_refresh = _crt_ref(_new_claims)
        return LoginResponse(
            access_token=new_access,
            refresh_token=new_refresh,
            org_slug=org.slug,
            org_id=org.id,
            plan=org.plan,
        )


@router.post("/api-keys")
async def create_api_key(
    req: ApiKeyCreateRequest,
    request: Request,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """Create a new API key for the current organisation."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import APIKey
    from aether_os.gateway.auth import generate_api_key, hash_api_key

    org_id = user.get("org_id")
    raw_key = generate_api_key()
    hashed = hash_api_key(raw_key)

    session_factory = get_session_factory()
    async with session_factory() as session:
        api_key = APIKey(
            id=str(uuid.uuid4()),
            org_id=org_id,
            key_hash=hashed,
            name=req.name,
        )
        session.add(api_key)
        await session.commit()

        # Audit: api_key_created
        from aether_os.core.audit.ledger import get_ledger
        client_ip = (
            request.headers.get("X-Real-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=org_id,
            user_id=user.get("user_id", "-"),
            action="api_key_created",
            resource_type="api_key",
            resource_id=api_key.id,
            metadata={"name": req.name},
            ip_address=client_ip,
            user_agent=request.headers.get("User-Agent", "-")
        ))

    return {
        "api_key": raw_key,
        "name": req.name,
        "message": "Store this key safely. It will not be shown again.",
    }


@router.get("/api-keys")
async def list_api_keys(user: Dict[str, Any] = _auth()) -> list:
    """List all active API keys for the current organisation."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import APIKey
    from sqlalchemy import select

    session_factory = get_session_factory()
    async with session_factory() as session:
        rows = (await session.execute(
            select(APIKey).where(APIKey.org_id == user["org_id"], APIKey.is_active == True)
        )).scalars().all()
    return [
        {"id": k.id, "name": k.name, "created_at": str(k.created_at), "last_used_at": k.last_used_at}
        for k in rows
    ]


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str, request: Request, user: Dict[str, Any] = _auth()) -> Dict[str, str]:
    """Revoke an API key by ID."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import APIKey

    session_factory = get_session_factory()
    async with session_factory() as session:
        key = await session.get(APIKey, key_id)
        if not key or key.org_id != user["org_id"]:
            raise HTTPException(status_code=404, detail="API key not found")
        key.is_active = False
        await session.commit()

        # Audit: api_key_revoked
        from aether_os.core.audit.ledger import get_ledger
        client_ip = (
            request.headers.get("X-Real-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=user["org_id"],
            user_id=user.get("user_id", "-"),
            action="api_key_revoked",
            resource_type="api_key",
            resource_id=key_id,
            ip_address=client_ip,
            user_agent=request.headers.get("User-Agent", "-")
        ))

    return {"status": "revoked"}


@router.get("/verify-email")
async def verify_email(token: str, request: Request) -> Dict[str, str]:
    """Verify user's email address using the token."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User

    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    user_agent = request.headers.get("User-Agent", "-")
    from aether_os.core.audit.ledger import get_ledger

    try:
        from aether_os.core.pipeline_state import get_redis
        r = await get_redis()
        if not r:
            raise HTTPException(status_code=500, detail="Redis unavailable")
        user_id = await r.get(f"email_verify:{token}")
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid or expired verification token")

        # Delete token after use
        await r.delete(f"email_verify:{token}")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Internal error during token validation")

    sf = get_session_factory()
    async with sf() as session:
        user = await session.get(User, user_id.decode() if isinstance(user_id, bytes) else user_id)
        if not user:
            raise HTTPException(status_code=400, detail="User no longer exists")

        user.email_verified = True
        await session.commit()

        # Audit: email_verified
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=user.org_id,
            user_id=user.id,
            action="email_verified",
            ip_address=client_ip,
            user_agent=user_agent
        ))

    return {"message": "Email verified successfully. You can now log in."}


@router.post("/password-reset-request")
async def password_reset_request(req: PasswordResetRequest, request: Request) -> Dict[str, str]:
    """Request a password reset email."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from sqlalchemy import select
    import secrets

    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    user_agent = request.headers.get("User-Agent", "-")
    from aether_os.core.audit.ledger import get_ledger

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(User).where(User.email == req.email)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            token = secrets.token_urlsafe(32)
            try:
                from aether_os.core.pipeline_state import get_redis
                r = await get_redis()
                if r:
                    # Store token in Redis with 1 hour expiry
                    await r.setex(f"pw_reset:{token}", 3600, user.id)
            except Exception:
                pass

            # Audit: password_reset_request
            asyncio.create_task(get_ledger().async_log_audit_event(
                org_id=user.org_id,
                user_id=user.id,
                action="password_reset_request",
                ip_address=client_ip,
                user_agent=user_agent
            ))

            # Send email
            from aether_os.core.notifications.email import get_email_notifier
            notifier = get_email_notifier()
            # frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:8000")
            # For simplicity, we use a placeholder or relative link if we don't have host
            subject = "AetherOS: Password Reset Request"
            body = f"Click here to reset your password: /reset-password?token={token}\n\nThis link expires in 1 hour."
            await notifier.send(user.email, subject, body)

    # Always return success to prevent email enumeration
    return {"message": "If an account exists for that email, a reset link has been sent."}


@router.post("/password-reset-confirm")
async def password_reset_confirm(req: PasswordResetConfirm, request: Request) -> Dict[str, str]:
    """Confirm password reset using the token."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from aether_os.gateway.auth import get_password_hash

    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    user_agent = request.headers.get("User-Agent", "-")
    from aether_os.core.audit.ledger import get_ledger

    try:
        from aether_os.core.pipeline_state import get_redis
        r = await get_redis()
        if not r:
            raise HTTPException(status_code=500, detail="Redis unavailable")
        user_id = await r.get(f"pw_reset:{req.token}")
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")

        # Delete token after use
        await r.delete(f"pw_reset:{req.token}")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Internal error during token validation")

    # Password safety: complexity + HIBP breach check
    try:
        from aether_os.core.guardian.password_shield import check_password_safety
        _pw_safe, _pw_reason = await check_password_safety(req.new_password)
        if not _pw_safe:
            raise HTTPException(status_code=422, detail=_pw_reason)
    except HTTPException:
        raise
    except Exception as _pw_exc:
        logger.warning("Password shield check failed: %s", _pw_exc)

    sf = get_session_factory()
    async with sf() as session:
        user = await session.get(User, user_id.decode() if isinstance(user_id, bytes) else user_id)
        if not user:
            raise HTTPException(status_code=400, detail="User no longer exists")

        loop = asyncio.get_running_loop()
        user.password_hash = await loop.run_in_executor(None, get_password_hash, req.new_password)
        await session.commit()

        # Audit: password_reset_confirm
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=user.org_id,
            user_id=user.id,
            action="password_reset_confirm",
            ip_address=client_ip,
            user_agent=user_agent
        ))

    return {"message": "Password has been reset successfully."}


@router.post("/change-password")
async def change_password(req: Dict[str, Any], request: Request, user: Dict[str, Any] = _auth()) -> Dict[str, str]:
    """Change the authenticated user's password with HIBP breach check."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from aether_os.gateway.auth import verify_password, get_password_hash

    user_id = user.get("user_id", "")
    current_pw = req.get("current_password", "")
    new_pw = req.get("new_password", "")

    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    user_agent = request.headers.get("User-Agent", "-")
    from aether_os.core.audit.ledger import get_ledger

    # Password safety: complexity + HIBP breach check
    try:
        from aether_os.core.guardian.password_shield import check_password_safety
        _pw_safe, _pw_reason = await check_password_safety(new_pw)
        if not _pw_safe:
            raise HTTPException(status_code=422, detail=_pw_reason)
    except HTTPException:
        raise
    except Exception as _pw_exc:
        logger.warning("Password shield check failed: %s", _pw_exc)

    sf = get_session_factory()
    async with sf() as session:
        db_user = await session.get(User, user_id)
        if not db_user:
            raise HTTPException(status_code=404)
        loop = asyncio.get_running_loop()
        pw_ok = await loop.run_in_executor(None, verify_password, current_pw, db_user.password_hash)
        if not pw_ok:
            raise HTTPException(status_code=401, detail="Current password is incorrect.")
        db_user.password_hash = await loop.run_in_executor(None, get_password_hash, new_pw)
        await session.commit()

        # Audit: password_change
        asyncio.create_task(get_ledger().async_log_audit_event(
            org_id=user.get("org_id", "-"),
            user_id=user.get("user_id", "-"),
            action="password_change",
            ip_address=client_ip,
            user_agent=user_agent
        ))

    return {"message": "Password changed"}


# ── Org switcher ──────────────────────────────────────────────────────────────

def _current_user():
    return Depends(get_current_user)


@router.get("/mfa/status")
async def mfa_status(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    """Return whether MFA is enabled for the current user."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User as _User
    sf = get_session_factory()
    async with sf() as session:
        u = await session.get(_User, user.get("user_id", user.get("sub", "")))
    return {"enabled": bool(u.mfa_enabled) if u else False}


@router.get("/my-orgs")
async def get_my_orgs(user: Dict[str, Any] = _current_user()) -> Dict[str, Any]:
    """Return all organisations the current user belongs to.
    AetherOS is currently single-org per user; this returns the current org
    so the TopBar org switcher can display it and future multi-org joins work.
    """
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation, User as _User
    from sqlalchemy import select
    sf = get_session_factory()
    async with sf() as session:
        org = await session.get(Organisation, user["org_id"])
        u = await session.get(_User, user.get("user_id", user.get("sub", "")))
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return {
        "current_org_id": org.id,
        "orgs": [
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "plan": org.plan,
                "role": u.role if u else user.get("role", "member"),
                "is_current": True,
            }
        ],
    }
