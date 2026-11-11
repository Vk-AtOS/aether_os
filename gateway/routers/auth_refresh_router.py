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
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from aether_os.core.audit.ledger import get_ledger
from aether_os.core.db import get_session_factory
from aether_os.core.models import Organisation, User
from aether_os.core.rate_limiter import get_client_ip
from aether_os.gateway.auth import decode_access_token
from aether_os.gateway.auth_refresh import consume_refresh_token, issue_token_pair

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
    """Exchange a refresh token for a new access + refresh pair (single use).

    Public on purpose: the refresh token in the body is the credential.
    """
    claims = decode_access_token(req.refresh_token)
    if not claims or claims.get("token_type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Audit: token_refresh
    asyncio.create_task(get_ledger().async_log_audit_event(
        org_id=claims.get("org_id", "-"),
        user_id=claims.get("user_id", "-"),
        action="token_refresh",
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent", "-")
    ))

    # Spend the token before anything is issued: revoked, replayed or unverifiable → no new pair.
    family = await consume_refresh_token(claims)

    async with get_session_factory()() as session:
        row = (
            await session.execute(
                select(User, Organisation).join(Organisation).where(User.id == claims.get("user_id"))
            )
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="User not found")
        user, org = row
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is disabled")

        new_access, new_refresh = issue_token_pair({
            "sub": user.email,
            "user_id": user.id,
            "org_id": org.id,
            "org_slug": org.slug,
            "role": user.role,
            "plan": org.plan,
        }, family=family)
        return LoginResponse(
            access_token=new_access,
            refresh_token=new_refresh,
            org_slug=org.slug,
            org_id=org.id,
            plan=org.plan,
        )
