"""Prime API — requests, the approval inbox and the deputy view.

HTTP only: who may see or decide what is settled in `aether_os.prime.approvals`.
Every endpoint needs a signed-in caller; deciding needs a person (not an API key).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers.prime_router import _delegation_out, _repo, _uid
from aether_os.prime import Action
from aether_os.prime.approvals import ApprovalService, RequestError, members
from aether_os.prime.authz import CURRENCY, Amount, Currency
from aether_os.prime.executors import DEFAULT_EXECUTOR
from aether_os.prime.ledger_view import by_delegation

router = APIRouter(prefix="/prime", tags=["prime"])

_approvals = ApprovalService(_repo)
_MAX_PARAMS_BYTES = 8_192


class RequestIn(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    amount: Optional[Amount] = None
    currency: Optional[Currency] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    executor: str = Field(default=DEFAULT_EXECUTOR, min_length=1, max_length=64)
    on_behalf_of: Optional[str] = Field(default=None, max_length=255)

    @field_validator("params")
    @classmethod
    def _small(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if len(json.dumps(v, default=str)) > _MAX_PARAMS_BYTES:
            raise ValueError("params is too large")
        return v


class DecisionIn(BaseModel):
    # The hash of the request as it was shown; the decision covers exactly that.
    request_hash: str = Field(min_length=64, max_length=64)
    reason: str = Field(default="", max_length=1000)


def _person(user: Dict[str, Any]) -> Tuple[str, List[str], str]:
    """(user id, identities a delegation may name them by, organisation id)."""
    uid = _uid(user)
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=403, detail="No organisation on this sign-in")
    email = str(user.get("sub") or "").strip().lower()
    return uid, [uid, email] if "@" in email else [uid], str(org_id)


def _http(e: RequestError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=str(e))


@router.post("/requests", status_code=201)
async def submit_request(
    body: RequestIn, user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Ask Prime to carry out an action. Prime decides; a person may have to approve.

    A person may only ask on their own behalf. An organisation API key (a system such
    as Velaris) may ask on behalf of any person in its own organisation, and gets no
    authority that person lacks: Prime checks that person's role for the action and
    executor (prime/service.py), and again at approval and before execution.
    """
    org_id = user.get("org_id")
    if user.get("user_id"):
        uid, _ids, org_id = _person(user)
        if body.on_behalf_of not in (None, uid):
            raise HTTPException(status_code=403, detail="You can only ask Prime on your own behalf")
        on_behalf_of = requested_by = uid
    else:
        if not org_id or not body.on_behalf_of or \
                body.on_behalf_of not in await members(org_id, [body.on_behalf_of]):
            raise HTTPException(status_code=403, detail="on_behalf_of must be a person in this organisation")
        on_behalf_of, requested_by = body.on_behalf_of, "system:api_key"
    action = Action(type=body.type, on_behalf_of=on_behalf_of, requested_by=requested_by,
                    amount=body.amount, params=body.params,
                    currency=body.currency or (CURRENCY if body.amount else None))
    try:
        return await _approvals.submit(action, org_id, body.executor)
    except RequestError as e:
        raise _http(e) from e


@router.get("/inbox")
async def inbox(
    state: Literal["pending", "decided", "expired", "all"] = "pending",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Requests waiting for the caller, as owner or as the active deputy of a delegation."""
    uid, ids, org_id = _person(user)
    return await _approvals.inbox(uid, ids, org_id, state=state, limit=limit, offset=offset)


@router.get("/requests/{request_id}")
async def get_request(
    request_id: str, user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    uid, ids, org_id = _person(user)
    try:
        return await _approvals.get(request_id, uid, ids, org_id)
    except RequestError as e:
        raise _http(e) from e


async def _decide(request_id: str, body: DecisionIn, user: Dict[str, Any],
                  approve: bool) -> Dict[str, Any]:
    uid, ids, org_id = _person(user)
    try:
        return await _approvals.decide(request_id, uid, ids, org_id, body.request_hash,
                                       approve=approve, reason=body.reason)
    except RequestError as e:
        raise _http(e) from e


@router.post("/requests/{request_id}/approve")
async def approve_request(
    request_id: str, body: DecisionIn, user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Approve exactly the request whose hash is quoted, then carry it out once."""
    return await _decide(request_id, body, user, approve=True)


@router.post("/requests/{request_id}/reject")
async def reject_request(
    request_id: str, body: DecisionIn, user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    return await _decide(request_id, body, user, approve=False)


@router.get("/deputies")
async def deputies(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Delegations the caller gave and those naming the caller as deputy, each with
    what was done under it according to the ledger."""
    uid, ids, org_id = _person(user)
    now = datetime.now(timezone.utc)
    given = await _repo.for_grantor(uid)
    received = await _repo.for_deputy(ids)
    # Only delegations from people in the caller's own organisation are shown.
    same_org = await members(org_id, {d.grantor for d in received})
    received = [d for d in received if d.grantor in same_org]
    activity = await by_delegation([d.id for d in given + received])
    return {
        "given": [{**_delegation_out(d, now), "activity": activity[d.id]}
                  for d in sorted(given, key=lambda d: d.valid_from, reverse=True)],
        # For a delegation someone else gave, the deputy sees only their own actions.
        "received": [{**_delegation_out(d, now),
                      "activity": [e for e in activity[d.id] if e["actor"] in ids]}
                     for d in sorted(received, key=lambda d: d.valid_from, reverse=True)],
    }
