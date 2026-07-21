"""
AetherOS — TOTP MFA Router (T6-03)
Routes:
  POST /auth/mfa/setup          — generate TOTP secret, return provisioning URI
  POST /auth/mfa/verify-setup   — confirm code, activate MFA on account
  POST /auth/mfa/confirm        — exchange mfa_token + TOTP code for real JWT
  POST /auth/mfa/disable        — verify code then disable MFA
Flow:
  1. User calls /auth/login → if mfa_enabled, returns {mfa_required: true, mfa_token: <short JWT>}
  2. Frontend shows MFA code input, submits to /auth/mfa/confirm
  3. On success, /auth/mfa/confirm returns the full LoginResponse JWT
"""
from __future__ import annotations
import logging
import os
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user
from aether_os.core.db import get_session_factory
from aether_os.core.models import User
from aether_os.core.models import User, Organisation
from aether_os.core.rate_limiter import _get_async_redis
from aether_os.core.rate_limiter import _get_async_redis, _redis_get_count
from aether_os.core.rate_limiter import _get_async_redis, _redis_incr_window
from aether_os.gateway.auth import create_refresh_token as _crt_mfa
from aether_os.gateway.auth import decode_access_token, create_access_token
from sqlalchemy import select
import pyotp  # optional dependency — only used when MFA is enabled; not installed in all deployments
logger = logging.getLogger(__name__)
mfa_router = APIRouter(prefix="/auth/mfa", tags=["mfa"])
_MFA_ISSUER = os.environ.get("MFA_ISSUER", "AetherOS")
_MFA_TOKEN_EXPIRE_MINUTES = 5
# ── TOTP replay prevention ────────────────────────────────────────────────────
async def _record_used_totp(user_id: str, code: str) -> None:
    """Record a used TOTP code in Redis with 90-second TTL to prevent replay."""
    try:
        r = await _get_async_redis()
        if r:
            key = f"mfa_used:{user_id}:{code}"
            await r.set(key, "1", ex=90)
    except Exception as exc:
        logger.warning("MFA replay prevention: Redis write failed: %s", exc)
async def _is_totp_code_used(user_id: str, code: str) -> bool:
    """Return True if this TOTP code was already used (replay detected)."""
    try:
        r = await _get_async_redis()
        if r:
            key = f"mfa_used:{user_id}:{code}"
            return bool(await r.exists(key))
        # Redis unavailable — fall back to allow (log warning)
        logger.warning("MFA replay check: Redis unavailable, skipping replay check for user %s", user_id)
        return False
    except Exception as exc:
        logger.warning("MFA replay prevention: Redis read failed: %s", exc)
        return False
# ── MFA rate limiting ─────────────────────────────────────────────────────────
async def _check_mfa_attempts(ip: str, max_attempts: int = 5, window: int = 300) -> bool:
    """Return True if the IP is within rate limit. False = locked out."""
    effective_ip = ip if ip and ip != "unknown" else "unknown_ip"
    try:
        r = await _get_async_redis()
        if r:
            count = await _redis_get_count(r, f"mfa_confirm:{effective_ip}", window)
            return count < max_attempts
        # Redis unavailable — deny on Redis failure for auth-critical endpoint
        logger.warning("MFA rate limit: Redis unavailable, denying MFA attempt from IP %s", effective_ip)
        return False
    except Exception as exc:
        logger.warning("MFA rate limit check failed: %s", exc)
        return False
async def _record_mfa_attempt(ip: str) -> None:
    """Increment the MFA attempt counter for this IP."""
    effective_ip = ip if ip and ip != "unknown" else "unknown_ip"
    try:
        r = await _get_async_redis()
        if r:
            await _redis_incr_window(r, f"mfa_confirm:{effective_ip}", 300)
    except Exception as exc:
        logger.warning("MFA rate limit record failed: %s", exc)
class MfaSetupResponse(BaseModel):
    provisioning_uri: str
    secret: str
class MfaCodeRequest(BaseModel):
    code: str
class MfaConfirmRequest(BaseModel):
    mfa_token: str
    code: str
def _get_totp(secret: str):
    try:
        return pyotp.TOTP(secret)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="pyotp not installed") from exc
# ── Setup ─────────────────────────────────────────────────────────────────────
@mfa_router.post("/setup", response_model=MfaSetupResponse)
async def mfa_setup(user_claims: Dict[str, Any] = Depends(get_current_user)) -> MfaSetupResponse:
    """Generate a new TOTP secret and store it (not yet enabled until verified)."""
    user_id = user_claims.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID missing from token")
    secret = pyotp.random_base32()
    sf = get_session_factory()
    async with sf() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.mfa_enabled:
            raise HTTPException(status_code=400, detail="MFA is already enabled. Disable it first.")
        user.mfa_secret = secret
        await session.commit()
    totp = _get_totp(secret)
    uri = totp.provisioning_uri(name=user_claims.get("sub", "user"), issuer_name=_MFA_ISSUER)
    return MfaSetupResponse(provisioning_uri=uri, secret=secret)
# ── Verify Setup ──────────────────────────────────────────────────────────────
@mfa_router.post("/verify-setup")
async def mfa_verify_setup(
    body: MfaCodeRequest,
    user_claims: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, str]:
    """Confirm the TOTP code and activate MFA on the account."""
    user_id = user_claims.get("user_id")
    sf = get_session_factory()
    async with sf() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not user.mfa_secret:
            raise HTTPException(status_code=400, detail="MFA setup not initiated. Call /auth/mfa/setup first.")
        if user.mfa_enabled:
            raise HTTPException(status_code=400, detail="MFA is already enabled.")
        totp = _get_totp(user.mfa_secret)
        if not totp.verify(body.code, valid_window=1):
            raise HTTPException(status_code=400, detail="Invalid TOTP code. Check your authenticator app.")
        user.mfa_enabled = True
        await session.commit()
    return {"message": "MFA enabled successfully"}
# ── Disable ───────────────────────────────────────────────────────────────────
@mfa_router.post("/disable")
async def mfa_disable(
    body: MfaCodeRequest,
    user_claims: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, str]:
    """Verify current TOTP code then disable MFA on the account."""
    user_id = user_claims.get("user_id")
    sf = get_session_factory()
    async with sf() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not user.mfa_enabled or not user.mfa_secret:
            raise HTTPException(status_code=400, detail="MFA is not enabled on this account.")
        totp = _get_totp(user.mfa_secret)
        if not totp.verify(body.code, valid_window=1):
            raise HTTPException(status_code=400, detail="Invalid TOTP code.")
        user.mfa_enabled = False
        user.mfa_secret = None
        await session.commit()
    return {"message": "MFA disabled successfully"}
# ── Confirm (login second factor) ─────────────────────────────────────────────
@mfa_router.post("/confirm")
async def mfa_confirm(request: Request, body: MfaConfirmRequest) -> Dict[str, Any]:
    """Exchange a short-lived mfa_token + TOTP code for a full JWT."""
    # SEC-012: Rate limit MFA confirm by client IP (5 attempts per 5 minutes)
    client_ip = request.client.host if request.client else "unknown"
    if not await _check_mfa_attempts(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many MFA attempts. Please wait before trying again.",
        )
    claims = decode_access_token(body.mfa_token)
    if not claims or not claims.get("mfa_pending"):
        raise HTTPException(status_code=401, detail="Invalid or expired MFA token")
    user_id = claims.get("user_id")
    sf = get_session_factory()
    async with sf() as session:
        row = (
            await session.execute(
                select(User, Organisation).join(Organisation).where(User.id == user_id)
            )
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        user, org = row
        if not user.mfa_enabled or not user.mfa_secret:
            raise HTTPException(status_code=400, detail="MFA not configured for this account")
        # SEC-011: Check for TOTP code replay before verifying
        if await _is_totp_code_used(user.id, body.code):
            await _record_mfa_attempt(client_ip)
            raise HTTPException(status_code=401, detail="TOTP code has already been used")
        totp = _get_totp(user.mfa_secret)
        if not totp.verify(body.code, valid_window=1):
            await _record_mfa_attempt(client_ip)
            raise HTTPException(status_code=401, detail="Invalid TOTP code")
        # Record the code as used to prevent replay attacks
        await _record_used_totp(user.id, body.code)
    _mfa_claims = {
        "sub": user.email,
        "user_id": user.id,
        "org_id": org.id,
        "org_slug": org.slug,
        "role": user.role,
        "plan": org.plan,
    }
    token = create_access_token(_mfa_claims)
    refresh = _crt_mfa(_mfa_claims)
    return {
        "access_token": token,
        "refresh_token": refresh,
        "token_type": "bearer",
        "org_slug": org.slug,
        "org_id": org.id,
        "plan": org.plan,
    }