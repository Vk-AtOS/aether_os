"""
AetherOS — SCIM 2.0 Router (T5-08)
GET    /scim/v2/Users
GET    /scim/v2/Users/{user_id}
POST   /scim/v2/Users
PUT    /scim/v2/Users/{user_id}
DELETE /scim/v2/Users/{user_id}
GET    /scim/v2/Groups
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["scim"])


def _current_user():
    from aether_os.gateway.api import get_current_user
    return Depends(get_current_user)


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
    user: Dict[str, Any] = _current_user(),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User as _User
    from sqlalchemy import select
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
    user: Dict[str, Any] = _current_user(),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User as _User
    sf = get_session_factory()
    async with sf() as session:
        u = await session.get(_User, user_id)
    if not u or u.org_id != user["org_id"] or u.deleted_at:
        raise HTTPException(status_code=404)
    return _scim_user(u)


@router.post("/scim/v2/Users")
async def scim_create_user(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """SCIM provision a new user into the org."""
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    import secrets as _sec
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User as _User
    from aether_os.gateway.auth import get_password_hash

    email = req.get("userName") or (req.get("emails") or [{}])[0].get("value")
    if not email:
        raise HTTPException(status_code=400, detail="userName or emails[0].value required")

    sf = get_session_factory()
    async with sf() as session:
        from sqlalchemy import select
        if (await session.execute(select(_User).where(_User.email == email))).scalar_one_or_none():
            raise HTTPException(status_code=409, detail="User already exists")
        new_user = _User(
            id=str(uuid.uuid4()),
            org_id=user["org_id"],
            email=email,
            password_hash=get_password_hash(_sec.token_urlsafe(24)),
            role="member",
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
    return JSONResponse(status_code=201, content=_scim_user(new_user))


@router.put("/scim/v2/Users/{user_id}")
async def scim_update_user(
    user_id: str,
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User as _User
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
    user: Dict[str, Any] = _current_user(),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User as _User
    from datetime import datetime as _dt
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
    user: Dict[str, Any] = _current_user(),
):
    if user.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403)
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation as _Org
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
