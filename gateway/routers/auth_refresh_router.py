"""
AetherOS — Auth Refresh Router

Token refresh endpoint. Split from auth_router.py to keep that file under 400 lines.

Routes
------
  POST /auth/refresh
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


# ── Pydantic models ────────────────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    refresh_token: str


class LoginResponse(BaseModel):
    access_token: str = ""
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    org_slug: str = ""
    org_id: str = ""
    plan: str = ""
    mfa_required: bool = False
    mfa_token: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

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
        except Exception as _redis_exc:
            logger.warning("Redis blacklist check failed during token refresh: %s", _redis_exc)

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
