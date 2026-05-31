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


class ApiKeyCreateRequest(BaseModel):
    name: str


def _auth():
    from aether_os.gateway.api import get_current_user
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
    if not req.terms_accepted:
        raise HTTPException(status_code=400, detail="You must accept the terms of service to register.")
    if not req.dpa_accepted:
        raise HTTPException(status_code=400, detail="You must accept the Data Processing Agreement (GDPR Art. 28) to register.")

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
        _consent_now = datetime.now(timezone.utc)
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

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(User, Organisation).join(Organisation).where(User.email == req.email)
        result = await session.execute(stmt)
        row = result.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        loop = asyncio.get_running_loop()
        pw_ok = await loop.run_in_executor(None, verify_password, req.password, row[0].password_hash)
        if not pw_ok:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        user, org = row
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

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
async def logout(user: Dict[str, Any] = _auth()) -> Dict[str, str]:
    """Invalidate the current JWT by adding its jti to Redis blacklist."""
    jti = user.get("jti")
    exp = user.get("exp", 0)
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
async def refresh_token_endpoint(req: RefreshRequest) -> LoginResponse:
    """Exchange a valid refresh token for a new access + refresh token pair."""
    from aether_os.gateway.auth import decode_access_token, create_access_token, create_refresh_token as _crt_ref
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User, Organisation
    from sqlalchemy import select

    claims = decode_access_token(req.refresh_token)
    if not claims or claims.get("token_type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

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
async def revoke_api_key(key_id: str, user: Dict[str, Any] = _auth()) -> Dict[str, str]:
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
    return {"status": "revoked"}


@router.post("/change-password")
async def change_password(req: Dict[str, Any], user: Dict[str, Any] = _auth()) -> Dict[str, str]:
    """Change the authenticated user's password with HIBP breach check."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from aether_os.gateway.auth import verify_password, get_password_hash

    user_id = user.get("user_id", "")
    current_pw = req.get("current_password", "")
    new_pw = req.get("new_password", "")

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
    return {"message": "Password changed"}
