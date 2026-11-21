"""
AetherOS — SCIM 2.0 Router (T5-08)
GET    /scim/v2/Users
GET    /scim/v2/Users/{user_id}
POST   /scim/v2/Users
PUT    /scim/v2/Users/{user_id}
PATCH  /scim/v2/Users/{user_id}   (Okta/Entra deactivate with active=false)
DELETE /scim/v2/Users/{user_id}
Groups, ServiceProviderConfig, ResourceTypes and Schemas: gateway/routers/scim_groups_router.py
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
import asyncio
import hashlib
import logging
import os
import re
import secrets
import uuid
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from aether_os.core.db import get_session_factory
from aether_os.core.models import Organisation
from aether_os.core.rate_limiter import get_client_ip, get_rate_limiter
from aether_os.core.models import User as _User
from aether_os.gateway.auth import get_password_hash
from aether_os.gateway.auth_refresh import revoke_user_sessions
from aether_os.gateway.policy_guard import enforce_seat
from aether_os.gateway.scim_patch import as_bool, attribute_changes, operations, scim_error
from datetime import datetime as _dt
from sqlalchemy import func, select
import bcrypt as _bcrypt
import secrets as _sec
_FILTER_USERNAME = re.compile(r'^\s*userName\s+eq\s+"([^"]*)"\s*$', re.IGNORECASE)
_FILTER_ANY = re.compile(r'^\s*(externalId)\s+eq\s+"[^"]*"\s*$', re.IGNORECASE)
logger = logging.getLogger(__name__)
LEGACY_PER_MINUTE = 30     # bcrypt compares of legacy (no sha256 lookup) tokens per client address per minute
router = APIRouter(tags=["scim"])
def _match_org_token(token: str, orgs) -> Optional[str]:
    """Blocking (bcrypt): run in a thread. Returns the org id whose SCIM token matches."""
    for org_id, token_hash in orgs:
        try:
            if _bcrypt.checkpw(token.encode(), token_hash.encode()):
                return org_id
        except Exception as _bce:
            logger.warning("SCIM bcrypt compare failed for org %s: %s", org_id, _bce)
    return None


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
    try:
        sf = get_session_factory()
        async with sf() as session:
            # Hot path: one indexed lookup on the token's sha256 (the token is 256 random bits). No bcrypt.
            found = (await session.execute(
                select(Organisation.id).where(
                    Organisation.scim_token_lookup == hashlib.sha256(token.encode()).hexdigest())
            )).scalar_one_or_none()
            if found:
                return {"org_id": found, "role": "admin", "sub": "scim-provisioner"}
            # Legacy: tokens issued before scim_token_lookup existed are checked until the org rotates.
            orgs = (await session.execute(
                select(Organisation).where(
                    Organisation.scim_token_lookup.is_(None),
                    Organisation.scim_token_hash.isnot(None))
            )).scalars().all()
        # bcrypt is ~250 ms of CPU per compare per legacy org: bounded per client address, or a wrong token is a
        # CPU-exhaustion tool (KAN-69 F20); and off the event loop, or one IdP sync stalls the worker.
        if orgs and not await get_rate_limiter().allow(f"scim_legacy:{get_client_ip(request)}", LEGACY_PER_MINUTE, 60):
            raise HTTPException(status_code=429, detail="SCIM: too many attempts", headers={"Retry-After": "60"})
        org_id = await asyncio.to_thread(_match_org_token, token, [(o.id, o.scim_token_hash) for o in orgs])
        if org_id:
            return {"org_id": org_id, "role": "admin", "sub": "scim-provisioner"}
    except HTTPException:
        raise
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
    filter: Optional[str] = None,
    user: Dict[str, Any] = Depends(_verify_scim_auth),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    sf = get_session_factory()
    async with sf() as session:
        scope = (_User.org_id == user["org_id"], _User.deleted_at == None)
        if filter:
            # IdPs look a user up by userName before creating it; ignoring the filter made every user "exist".
            m = _FILTER_USERNAME.match(filter)
            if m:
                scope += (func.lower(_User.email) == m.group(1).lower(),)
            elif _FILTER_ANY.match(filter):
                scope += (_User.id == "",)  # externalId and other attributes: we store none, so nothing matches
            else:
                raise scim_error(400, "Unsupported filter; supported: userName eq \"value\"", "invalidFilter")
        total = (await session.execute(select(func.count()).select_from(_User).where(*scope))).scalar_one()
        rows = (await session.execute(
            select(_User).where(*scope).order_by(_User.id)
            .offset(max(startIndex, 1) - 1).limit(min(max(count, 0), 100))
        )).scalars().all()
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total,  # all matching users, not the size of this page (RFC 7644 3.4.2)
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
    await enforce_seat(user["org_id"], "scim")  # 402 quota_seats: the IdP cannot exceed the plan's seats
    sf = get_session_factory()
    async with sf() as session:
        if (await session.execute(select(_User).where(_User.email == email))).scalar_one_or_none():
            raise scim_error(409, "User already exists", "uniqueness")
        new_user = _User(
            id=str(uuid.uuid4()),
            org_id=user["org_id"],
            email=email,
            password_hash=await asyncio.to_thread(get_password_hash, _sec.token_urlsafe(24)),
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
        # displayName has no column: it used to be written into user_preferences, destroying the
        # user's saved preferences. It is accepted and ignored.
        if "active" in req:
            await _set_active(u, as_bool(req["active"]))
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
    await revoke_user_sessions(user_id)  # the account stops working now, not when its token expires


async def _set_active(u, active: bool) -> None:
    """Flip a user's active flag. Reactivation needs a free seat; deactivation ends every session."""
    if active and not u.is_active:
        await enforce_seat(u.org_id, "scim")
    u.is_active = active
    if not active:
        await revoke_user_sessions(u.id)


@router.patch("/scim/v2/Users/{user_id}")
async def scim_patch_user(
    user_id: str,
    req: Dict[str, Any],
    user: Dict[str, Any] = Depends(_verify_scim_auth),
):
    """RFC 7644 3.5.2. Supports active and userName; other attributes are accepted and ignored
    (they have no column) so an IdP's full-profile patches do not fail."""
    changes = list(attribute_changes(operations(req)))
    sf = get_session_factory()
    async with sf() as session:
        u = await session.get(_User, user_id)
        if not u or u.org_id != user["org_id"] or u.deleted_at:
            raise scim_error(404, "User not found")
        for op, attr, value in changes:
            if attr == "active" and op != "remove":
                await _set_active(u, as_bool(value))
            elif attr in ("username", "emails[type eq \"work\"].value") and op != "remove":
                email = str(value or "").strip()
                if not email:
                    raise scim_error(400, "userName must not be empty", "invalidValue")
                if email != u.email:
                    taken = (await session.execute(select(_User.id).where(_User.email == email))).first()
                    if taken:
                        raise scim_error(409, "userName already in use", "uniqueness")
                    u.email = email
        await session.commit()
        await session.refresh(u)
    return _scim_user(u)
