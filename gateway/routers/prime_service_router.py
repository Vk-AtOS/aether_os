"""Prime service API — what a connected system (Velaris) asks of Prime.

Organisation API keys only: a signed-in person is refused (403), and the key's organisation
must own whatever is asked about. Nothing here changes a request; decisions are made by
people in the inbox. authorize-read is ledgered, grants and refusals alike, and a decision
that cannot be ledgered is not given (503).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from aether_os.core.audit import chain as audit_chain
from aether_os.core.velaris.roles import READ_OTHERS, velaris_roles
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers.prime_inbox_router import _approvals, _http
from aether_os.prime.approvals import RequestError
from aether_os.prime.repository import person_in_org

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/prime/service", tags=["prime-service"])

VELARIS_EXECUTOR = "velaris.flow"
SYSTEM_ACTOR = "system:api_key"


class CallerIn(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    org: str = Field(min_length=1, max_length=255)
    roles: List[str] = Field(default_factory=list, max_length=50)    # what Velaris holds; not trusted
    employee_id: Optional[str] = Field(default=None, max_length=255)


class ReadIn(BaseModel):
    caller: CallerIn
    category: str = Field(min_length=1, max_length=64)
    subject_id: Optional[str] = Field(default=None, max_length=255)
    org: Optional[str] = Field(default=None, max_length=255)


def _key_org(user: Dict[str, Any]) -> str:
    """The organisation of an org API key; anything else is refused."""
    org_id = user.get("org_id")
    if user.get("user_id") or user.get("role") != "api" or not org_id:
        raise HTTPException(status_code=403, detail="This endpoint is for an organisation API key")
    return str(org_id)


@router.get("/requests/{request_id}")
async def service_request(request_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """The same view as GET /prime/requests/{id} (request_hash, state, execution, decided_by),
    for a Velaris request of this key's organisation."""
    org_id = _key_org(user)
    try:
        return await _approvals.service_view(request_id, org_id, VELARIS_EXECUTOR)
    except RequestError as e:
        raise _http(e) from e


async def _read_decision(org_id: str, body: ReadIn) -> tuple[bool, str]:
    """Deny by default. Roles are re-derived from the person's stored organisation role
    (the roles Velaris sends are ignored), by the same table as the Velaris assertion."""
    if body.caller.org != org_id:
        return False, "caller belongs to another organisation"
    if body.org is not None and body.org != org_id:
        return False, "data belongs to another organisation"
    allowed_roles = READ_OTHERS.get(body.category)
    if allowed_roles is None:
        return False, f"unknown data category '{body.category}'"
    person = await person_in_org(org_id, body.caller.id)
    if person is None:
        return False, "not an active person in this organisation"
    held = sorted(velaris_roles(person[0]) & allowed_roles)
    if held:
        return True, f"role {held[0]}"
    # ponytail: AetherOS users have no linked employee record, so there is no "own record" case.
    return False, "no role that may read other people's records of this category"


@router.post("/authorize-read")
async def authorize_read(body: ReadIn, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """{caller, category, subject_id, org} -> {allowed, reason}."""
    org_id = _key_org(user)
    try:
        allowed, reason = await _read_decision(org_id, body)
    except Exception as e:  # the lookup failed: refuse, and say so in the log
        logger.warning("authorize-read lookup failed: %s", e)
        allowed, reason = False, "the decision could not be made"
    try:
        await audit_chain.append(actor=SYSTEM_ACTOR, action="prime.service.authorize_read", payload={
            "org_id": org_id, "caller": body.caller.id, "category": body.category,
            "subject_id": body.subject_id, "allowed": allowed, "reason": reason})
    except Exception as e:
        logger.error("authorize-read could not be ledgered: %s", e)
        raise HTTPException(status_code=503, detail="The decision could not be recorded") from None
    return {"allowed": allowed, "reason": reason}
