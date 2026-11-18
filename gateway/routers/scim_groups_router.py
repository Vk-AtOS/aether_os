"""
AetherOS — SCIM 2.0 Groups and discovery (KAN-163)

GET    /scim/v2/ServiceProviderConfig | ResourceTypes | Schemas   what IdP connectors probe first
GET    /scim/v2/Groups[?filter=displayName eq "x"]                 paginated
POST   /scim/v2/Groups                                              create (with members)
GET    /scim/v2/Groups/{id}
PUT    /scim/v2/Groups/{id}                                         replace name and members
PATCH  /scim/v2/Groups/{id}                                         add/remove/replace members, rename
DELETE /scim/v2/Groups/{id}

Same SCIM bearer auth as scim_router. A group records membership as the IdP sees it; it does NOT grant
a role (roles stay under admin control), so an IdP group named "admin" cannot escalate anyone.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select

from aether_os.core.db import get_session_factory
from aether_os.core.models import User
from aether_os.core.scim_models import ScimGroup, ScimGroupMember
from aether_os.gateway.routers.scim_router import _verify_scim_auth
from aether_os.gateway.scim_patch import attribute_changes, operations, scim_error

router = APIRouter(tags=["scim"])
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
MAX_MEMBERS = 1000          # members returned per group and accepted per request
_FILTER_NAME = re.compile(r'^\s*displayName\s+eq\s+"([^"]*)"\s*$', re.IGNORECASE)
_MEMBER_PATH = re.compile(r'^members\[value eq "([^"]+)"\]$', re.IGNORECASE)


def _require_admin(user: Dict[str, Any]) -> None:
    if user.get("role") not in ("owner", "admin"):
        raise scim_error(403, "Forbidden")


async def _resource(session, g: ScimGroup) -> Dict[str, Any]:
    rows = (await session.execute(
        select(User.id, User.email).join(ScimGroupMember, ScimGroupMember.user_id == User.id)
        .where(ScimGroupMember.group_id == g.id).order_by(User.id).limit(MAX_MEMBERS))).all()
    return {"schemas": [GROUP_SCHEMA], "id": g.id, "displayName": g.display_name,
            "members": [{"value": uid, "display": email} for uid, email in rows],
            "meta": {"resourceType": "Group", "created": g.created_at}}


async def _get(session, group_id: str, org_id: str) -> ScimGroup:
    g = await session.get(ScimGroup, group_id)
    if not g or g.org_id != org_id:
        raise scim_error(404, "Group not found")
    return g


async def _valid_member_ids(session, org_id: str, raw: Any) -> List[str]:
    """User ids from a members value; every one must be an active-or-not, non-deleted user of THIS org."""
    items = raw if isinstance(raw, list) else [raw]
    ids = [str(m.get("value")) for m in items if isinstance(m, dict) and m.get("value")]
    if len(ids) > MAX_MEMBERS:
        raise scim_error(400, f"At most {MAX_MEMBERS} members per request", "tooMany")
    if not ids:
        return []
    found = set((await session.execute(
        select(User.id).where(User.org_id == org_id, User.deleted_at.is_(None), User.id.in_(ids)))).scalars())
    missing = [i for i in ids if i not in found]
    if missing:
        raise scim_error(400, f"Unknown member(s): {missing[:5]}", "invalidValue")
    return list(dict.fromkeys(ids))


async def _add(session, g: ScimGroup, ids: List[str]) -> None:
    have = set((await session.execute(
        select(ScimGroupMember.user_id).where(ScimGroupMember.group_id == g.id))).scalars())
    for uid in ids:
        if uid not in have:
            session.add(ScimGroupMember(group_id=g.id, user_id=uid, org_id=g.org_id))


async def _name_taken(session, org_id: str, name: str, except_id: str = "") -> bool:
    q = select(ScimGroup.id).where(ScimGroup.org_id == org_id, ScimGroup.display_name == name)
    found = (await session.execute(q)).scalar_one_or_none()
    return bool(found and found != except_id)


def _name(req: Dict[str, Any]) -> str:
    name = str(req.get("displayName") or "").strip()
    if not 1 <= len(name) <= 255:
        raise scim_error(400, "displayName is required (1-255 characters)", "invalidValue")
    return name


@router.get("/scim/v2/ServiceProviderConfig")
async def service_provider_config(user: Dict[str, Any] = Depends(_verify_scim_auth)):
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True}, "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 100}, "changePassword": {"supported": False},
        "sort": {"supported": False}, "etag": {"supported": False},
        "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer token",
                                   "description": "Per-organisation SCIM token (rotate in Settings > Security)",
                                   "primary": True}],
    }


@router.get("/scim/v2/ResourceTypes")
async def resource_types(user: Dict[str, Any] = Depends(_verify_scim_auth)):
    res = [{"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"], "id": n, "name": n,
            "endpoint": f"/{n}s", "schema": f"urn:ietf:params:scim:schemas:core:2.0:{n}"} for n in ("User", "Group")]
    return {"schemas": [LIST_SCHEMA], "totalResults": 2, "startIndex": 1, "itemsPerPage": 2, "Resources": res}


@router.get("/scim/v2/Schemas")
async def schemas(user: Dict[str, Any] = Depends(_verify_scim_auth)):
    res = [
        {"id": "urn:ietf:params:scim:schemas:core:2.0:User", "name": "User",
         "attributes": [{"name": "userName", "type": "string", "required": True, "uniqueness": "server"},
                        {"name": "active", "type": "boolean"}, {"name": "emails", "type": "complex", "multiValued": True}]},
        {"id": GROUP_SCHEMA, "name": "Group",
         "attributes": [{"name": "displayName", "type": "string", "required": True},
                        {"name": "members", "type": "complex", "multiValued": True}]},
    ]
    return {"schemas": [LIST_SCHEMA], "totalResults": 2, "startIndex": 1, "itemsPerPage": 2, "Resources": res}


@router.get("/scim/v2/Groups")
async def list_groups(startIndex: int = 1, count: int = 50, filter: Optional[str] = None,
                      user: Dict[str, Any] = Depends(_verify_scim_auth)):
    _require_admin(user)
    scope = (ScimGroup.org_id == user["org_id"],)
    if filter:
        m = _FILTER_NAME.match(filter)
        if not m:
            raise scim_error(400, 'Unsupported filter; supported: displayName eq "value"', "invalidFilter")
        scope += (ScimGroup.display_name == m.group(1),)
    async with get_session_factory()() as session:
        total = (await session.execute(select(func.count()).select_from(ScimGroup).where(*scope))).scalar_one()
        rows = (await session.execute(select(ScimGroup).where(*scope).order_by(ScimGroup.id)
                .offset(max(startIndex, 1) - 1).limit(min(max(count, 0), 100)))).scalars().all()
        resources = [await _resource(session, g) for g in rows]
    return {"schemas": [LIST_SCHEMA], "totalResults": total, "startIndex": startIndex,
            "itemsPerPage": len(resources), "Resources": resources}


@router.post("/scim/v2/Groups")
async def create_group(req: Dict[str, Any], user: Dict[str, Any] = Depends(_verify_scim_auth)):
    _require_admin(user)
    name, org_id = _name(req), user["org_id"]
    async with get_session_factory()() as session:
        if await _name_taken(session, org_id, name):
            raise scim_error(409, "A group with this displayName already exists", "uniqueness")
        ids = await _valid_member_ids(session, org_id, req.get("members") or [])
        g = ScimGroup(id=str(uuid.uuid4()), org_id=org_id, display_name=name)
        session.add(g)
        await session.flush()
        await _add(session, g, ids)
        await session.commit()
        return JSONResponse(status_code=201, content=await _resource(session, g))


@router.get("/scim/v2/Groups/{group_id}")
async def get_group(group_id: str, user: Dict[str, Any] = Depends(_verify_scim_auth)):
    _require_admin(user)
    async with get_session_factory()() as session:
        return await _resource(session, await _get(session, group_id, user["org_id"]))


@router.put("/scim/v2/Groups/{group_id}")
async def replace_group(group_id: str, req: Dict[str, Any], user: Dict[str, Any] = Depends(_verify_scim_auth)):
    _require_admin(user)
    name = _name(req)
    async with get_session_factory()() as session:
        g = await _get(session, group_id, user["org_id"])
        if await _name_taken(session, g.org_id, name, g.id):
            raise scim_error(409, "A group with this displayName already exists", "uniqueness")
        ids = await _valid_member_ids(session, g.org_id, req.get("members") or [])
        g.display_name = name
        await session.execute(delete(ScimGroupMember).where(ScimGroupMember.group_id == g.id))
        await _add(session, g, ids)
        await session.commit()
        return await _resource(session, g)


@router.patch("/scim/v2/Groups/{group_id}")
async def patch_group(group_id: str, req: Dict[str, Any], user: Dict[str, Any] = Depends(_verify_scim_auth)):
    _require_admin(user)
    changes = list(attribute_changes(operations(req)))
    async with get_session_factory()() as session:
        g = await _get(session, group_id, user["org_id"])
        for op, attr, value in changes:
            if attr == "displayname" and op != "remove":
                name = _name({"displayName": value})
                if await _name_taken(session, g.org_id, name, g.id):
                    raise scim_error(409, "A group with this displayName already exists", "uniqueness")
                g.display_name = name
            elif attr == "members":
                if op == "remove" and value is None:        # remove the whole member list
                    await session.execute(delete(ScimGroupMember).where(ScimGroupMember.group_id == g.id))
                    continue
                ids = await _valid_member_ids(session, g.org_id, value)
                if op == "replace":
                    await session.execute(delete(ScimGroupMember).where(ScimGroupMember.group_id == g.id))
                if op == "remove":
                    await session.execute(delete(ScimGroupMember).where(
                        ScimGroupMember.group_id == g.id, ScimGroupMember.user_id.in_(ids)))
                else:
                    await _add(session, g, ids)
            elif (m := _MEMBER_PATH.match(attr)) and op == "remove":   # Entra: members[value eq "<id>"]
                await session.execute(delete(ScimGroupMember).where(
                    ScimGroupMember.group_id == g.id, ScimGroupMember.user_id == m.group(1)))
        await session.commit()
        return await _resource(session, g)


@router.delete("/scim/v2/Groups/{group_id}", status_code=204)
async def delete_group(group_id: str, user: Dict[str, Any] = Depends(_verify_scim_auth)):
    _require_admin(user)
    async with get_session_factory()() as session:
        g = await _get(session, group_id, user["org_id"])
        await session.execute(delete(ScimGroupMember).where(ScimGroupMember.group_id == g.id))
        await session.delete(g)
        await session.commit()
