"""
AetherOS — Auth Router

Authentication and API key management.
"""
from __future__ import annotations
import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    org_name: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    org_slug: str
    org_id: str
    plan: str


class ApiKeyCreateRequest(BaseModel):
    name: str


def _auth():
    from aether_os.gateway.api import get_current_user
    return Depends(get_current_user)


@router.post("/register", response_model=LoginResponse)
async def register(req: RegisterRequest, request: Request) -> LoginResponse:
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation, User
    from aether_os.gateway.auth import get_password_hash, create_access_token
    from aether_os.core.rate_limiter import get_rate_limiter
    from sqlalchemy import select

    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or "unknown"
    )
    rl = get_rate_limiter()
    rl.record_registration_attempt(client_ip)
    if not rl.check_registration_attempts(client_ip):
        raise HTTPException(status_code=429, detail="Too many registration attempts.")

    if len(req.password) < 10:
        raise HTTPException(status_code=422, detail="Password must be at least 10 characters.")

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(User).where(User.email == req.email)
        if (await session.execute(stmt)).scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")

        slug = req.org_name.lower().replace(" ", "-")
        org = Organisation(id=str(uuid.uuid4()), name=req.org_name, slug=slug, plan="trial")
        session.add(org)
        user = User(
            id=str(uuid.uuid4()),
            org_id=org.id,
            email=req.email,
            password_hash=get_password_hash(req.password),
            role="owner",
        )
        session.add(user)
        await session.commit()

    token = create_access_token({
        "sub": user.email, "user_id": user.id,
        "org_id": org.id, "org_slug": org.slug,
        "role": user.role, "plan": org.plan,
    })
    return LoginResponse(access_token=token, org_slug=org.slug, org_id=org.id, plan=org.plan)


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request) -> LoginResponse:
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation, User
    from aether_os.gateway.auth import verify_password, create_access_token
    from aether_os.core.rate_limiter import get_rate_limiter
    from sqlalchemy import select

    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or "unknown"
    )
    rl = get_rate_limiter()
    rl.record_login_attempt(client_ip)
    if not rl.check_login_attempts(client_ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Wait 15 minutes.")

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(User, Organisation).join(Organisation).where(User.email == req.email)
        row = (await session.execute(stmt)).fetchone()
        if not row or not verify_password(req.password, row[0].password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        user, org = row

    token = create_access_token({
        "sub": user.email, "user_id": user.id,
        "org_id": org.id, "org_slug": org.slug,
        "role": user.role, "plan": org.plan,
    })
    return LoginResponse(access_token=token, org_slug=org.slug, org_id=org.id, plan=org.plan)


@router.post("/api-keys")
async def create_api_key(
    req: ApiKeyCreateRequest,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import APIKey
    from aether_os.gateway.auth import generate_api_key, hash_api_key

    org_id = user.get("org_id")
    raw_key = generate_api_key()
    hashed = hash_api_key(raw_key)
    session_factory = get_session_factory()
    async with session_factory() as session:
        api_key = APIKey(
            id=str(uuid.uuid4()), org_id=org_id,
            key_hash=hashed, name=req.name, is_active=True,
        )
        session.add(api_key)
        await session.commit()
    return {"id": api_key.id, "key": raw_key, "name": req.name,
            "note": "Store this key securely — it will not be shown again."}


@router.get("/api-keys")
async def list_api_keys(user: Dict[str, Any] = _auth()) -> list:
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import APIKey
    from sqlalchemy import select
    session_factory = get_session_factory()
    async with session_factory() as session:
        rows = (await session.execute(
            select(APIKey).where(APIKey.org_id == user["org_id"], APIKey.is_active == True)
        )).scalars().all()
    return [{"id": k.id, "name": k.name, "created_at": str(k.created_at),
             "last_used_at": k.last_used_at} for k in rows]


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str, user: Dict[str, Any] = _auth()) -> Dict[str, str]:
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


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(user: Dict[str, Any] = _auth()) -> LoginResponse:
    """
    Issue a fresh 7-day JWT using the current valid token as proof of identity.
    Clients should call this before their token expires to avoid re-login.
    Recommended: call when token age > 6 days (check 'iat' claim).
    """
    from aether_os.gateway.auth import create_access_token
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from sqlalchemy import select

    org_id  = user.get("org_id")
    user_id = user.get("user_id") or user.get("sub", "")

    # Load fresh user data so revoked/changed roles are reflected in new token
    session_factory = get_session_factory()
    async with session_factory() as session:
        db_user = await session.get(User, user_id)
        if not db_user or not db_user.is_active:
            raise HTTPException(status_code=401, detail="Account inactive or not found")

    token_data = {
        "sub":      db_user.id,
        "user_id":  db_user.id,
        "org_id":   db_user.org_id,
        "email":    db_user.email,
        "role":     db_user.role,
        "plan":     user.get("plan", "trial"),
        "org_slug": user.get("org_slug", ""),
    }
    new_token = create_access_token(token_data)  # 7-day TTL (default)
    return LoginResponse(
        access_token=new_token,
        token_type="bearer",
        user_id=db_user.id,
        org_id=db_user.org_id,
        role=db_user.role,
    )
