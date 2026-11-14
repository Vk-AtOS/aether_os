"""
AetherOS — SCIM 2.0 Router (T5-08)
GET    /scim/v2/Users
GET    /scim/v2/Users/{user_id}
POST   /scim/v2/Users
PUT    /scim/v2/Users/{user_id}
DELETE /scim/v2/Users/{user_id}
GET    /scim/v2/Groups
Auth: dedicated SCIM Bearer token only. A user session JWT is never accepted:
provisioning creates and deactivates accounts, so it must not be reachable with
a credential every signed-in user holds.
Priority:
  1. SCIM_BEARER_TOKEN env var (static token — simplest for single-tenant)
  2. Organisation.scim_token_hash (per-org token from /settings/scim/rotate)
IdP setup (Okta / Azure AD / Google):
  - Bearer token: value of SCIM_BEARER_TOKEN (or per-org token from /settings/scim)
  - Base URL: https://your-domain/api/scim/v2
  - Set SCIM_ORG_ID to the AetherOS org UUID that the IdP should provision into.
"""
from __future__ import annotations
import logging
import os
import secrets
import uuid
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from aether_os.core.db import get_session_factory
from aether_os.core.models import Organisation
from aether_os.core.models import Organisation as _Org
from aether_os.core.models import User as _User
from aether_os.gateway.auth import get_password_hash
from datetime import datetime as _dt
from sqlalchemy import select
import bcrypt as _bcrypt
import secrets as _sec
logger = logging.getLogger(__name__)
router = APIRouter(tags=["scim"])
async def _verify_scim_auth(request: Request) -> Dict[str, Any]:
    """
    Dedicated SCIM auth dependency — accepts only a provisioning Bearer token.
    Priority:
    1. SCIM_BEARER_TOKEN env var (static token — IdP mode, single-tenant).
    2. Organisation.scim_token_hash (per-org token — multi-tenant / UI-managed).
    Anything else, including a valid user JWT, is 401.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="SCIM: Bearer token required",
            headers={"WWW-Authenticate": 'Bearer realm="SCIM"'},
        )
    token = auth_header[7:]
    # 1. Env-var static token (simplest setup — generate with secrets.token_urlsafe(32))
    static = os.environ.get("SCIM_BEARER_TOKEN", "").strip()
    if static and secrets.compare_digest(token.encode(), static.encode()):
        scim_org_id = os.getenv("SCIM_ORG_ID", "").strip()
        if not scim_org_id:
            raise HTTPException(
                status_code=503,
                detail=(
                    "SCIM provisioning is misconfigured: "
                    "set SCIM_ORG_ID env var to the target organisation UUID."
                ),
            )
        return {"org_id": scim_org_id, "role": "admin", "sub": "scim-provisioner"}
    # 2. Per-org DB token (rotatable via /settings/scim)
    # DB-H1: scim_token_hash stores a bcrypt hash — never compare plaintext stored value
    try:
        sf = get_session_factory()
        async with sf() as session:
            # Prefer hashed tokens; fall back to legacy plaintext scim_token for migration
            orgs = (await session.execute(
                select(Organisation).where(
                    Organisation.scim_token_hash.isnot(None) | Organisation.scim_token.isnot(None)
                )
            )).scalars().all()
        for org in orgs:
            # Check hashed token first (new path)
            if org.scim_token_hash:
                try:
                    if _bcrypt.checkpw(token.encode(), org.scim_token_hash.encode()):
                        return {"org_id": org.id, "role": "admin", "sub": "scim-provisioner"}
                except Exception as _bce:
                    logger.warning("SCIM bcrypt compare failed for org %s: %s", org.id, _bce)
            # Legacy plaintext fallback (only during migration window)
            elif org.scim_token and secrets.compare_digest(token.encode(), org.scim_token.encode()):
                logger.warning(
                    "SCIM: org %s is using deprecated plaintext scim_token — "
                    "rotate via /settings/scim to migrate to hashed storage", org.id
                )
                return {"org_id": org.id, "role": "admin", "sub": "scim-provisioner"}
    except Exception as exc:
        # Lookup failure is a denial, never a reason to try another credential type.
        logger.warning("SCIM per-org token lookup failed: %s", exc)
    raise HTTPException(
        status_code=401,
        detail="SCIM: invalid Bearer token",
        headers={"WWW-Authenticate": 'Bearer realm="SCIM"'},
    )
def _scim_user(u) -> dict:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": u.id,
        "userName": u.email,
        "displayName": getattr(u, "name", u.email),
        "active": u.is_active and not u.deleted_at,
        "emails": [{"value": u.email, "primary": True}],
        "meta": {
            "resourceType": "User",
            "created": str(u.created_at),
        },
    }
@router.get("/scim/v2/Users")
async def scim_list_users(
    startIndex: int = 1,
    count: int = 50,
    user: Dict[str, Any] = Depends(_verify_scim_auth),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    sf = get_session_factory()
    async with sf() as session:
        rows = (await session.execute(
            select(_User)
            .where(_User.org_id == user["org_id"], _User.deleted_at == None)
            .offset(startIndex - 1).limit(min(count, 100))
        )).scalars().all()
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": len(rows),
        "startIndex": startIndex,
        "itemsPerPage": len(rows),
        "Resources": [_scim_user(u) for u in rows],
    }
@router.get("/scim/v2/Users/{user_id}")
async def scim_get_user(
    user_id: str,
    user: Dict[str, Any] = Depends(_verify_scim_auth),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    sf = get_session_factory()
    async with sf() as session:
        u = await session.get(_User, user_id)
    if not u or u.org_id != user["org_id"] or u.deleted_at:
        raise HTTPException(status_code=404)
    return _scim_user(u)
@router.post("/scim/v2/Users")
async def scim_create_user(
    req: Dict[str, Any],
    user: Dict[str, Any] = Depends(_verify_scim_auth),
):
    """SCIM provision a new user into the org."""
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    email = req.get("userName") or (req.get("emails") or [{}])[0].get("value")
    if not email:
        raise HTTPException(status_code=400, detail="userName or emails[0].value required")
    sf = get_session_factory()
    async with sf() as session:
        if (await session.execute(select(_User).where(_User.email == email))).scalar_one_or_none():
            raise HTTPException(status_code=409, detail="User already exists")
        new_user = _User(
            id=str(uuid.uuid4()),
            org_id=user["org_id"],
            email=email,
            password_hash=get_password_hash(_sec.token_urlsafe(24)),
            role="member",
            email_verified=True,  # provisioned by the org's IdP/admin; no password login exists
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
    return JSONResponse(status_code=201, content=_scim_user(new_user))
@router.put("/scim/v2/Users/{user_id}")
async def scim_update_user(
    user_id: str,
    req: Dict[str, Any],
    user: Dict[str, Any] = Depends(_verify_scim_auth),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    sf = get_session_factory()
    async with sf() as session:
        u = await session.get(_User, user_id)
        if not u or u.org_id != user["org_id"] or u.deleted_at:
            raise HTTPException(status_code=404)
        if "active" in req:
            u.is_active = bool(req["active"])
        if "displayName" in req:
            u.user_preferences = req["displayName"]
        await session.commit()
        await session.refresh(u)
    return _scim_user(u)
@router.delete("/scim/v2/Users/{user_id}", status_code=204)
async def scim_delete_user(
    user_id: str,
    user: Dict[str, Any] = Depends(_verify_scim_auth),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    sf = get_session_factory()
    async with sf() as session:
        u = await session.get(_User, user_id)
        if not u or u.org_id != user["org_id"]:
            raise HTTPException(status_code=404)
        u.deleted_at = _dt.utcnow()
        u.is_active = False
        await session.commit()
@router.get("/scim/v2/Groups")
async def scim_list_groups(
    user: Dict[str, Any] = Depends(_verify_scim_auth),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    sf = get_session_factory()
    async with sf() as session:
        org = await session.get(_Org, user["org_id"])
    if not org:
        raise HTTPException(status_code=404)
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": 1,
        "startIndex": 1,
        "itemsPerPage": 1,
        "Resources": [{
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "id": org.id,
            "displayName": org.name,
            "meta": {"resourceType": "Group", "created": str(org.created_at)},
        }],
    }