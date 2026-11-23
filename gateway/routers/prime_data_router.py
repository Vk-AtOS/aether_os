"""Prime API — "Prime and your data" (KAN-228): consent, see, export and erase what Prime learned about you.

Employee only (owner decision, 22 Nov 2026): `{person}` is "me" or the caller's own user id. Any other person is 403
for EVERY role, owner, admin and superadmin included, and the refused attempt is ledgered; there is no manager or
admin view of anyone's learned data. API keys are refused (no person behind them). Consent changes, exports and
erasures are ledgered by prime/consent.py and prime/learned.py. The organisation's retention period is the one
organisation-wide setting here: anyone may read it, an owner or admin may change it.
The router's lifespan runs the purge job (prime/retention.py).
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from aether_os.core.audit import chain as audit_chain
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers.prime_router import _uid
from aether_os.prime import consent, learned, retention

router = APIRouter(tags=["prime-data"], lifespan=retention.periodic_lifespan)

Switch = Literal["all", "git", "jira", "calendar", "attendance"]
Source = Literal["git", "jira", "calendar", "attendance"]


class ConsentIn(BaseModel):
    source: Switch
    enabled: bool
    notice_version: str = Field(default="", max_length=32)   # the notice the person was shown


class RetentionIn(BaseModel):
    retention_days: int = Field(ge=retention.MIN_RETENTION_DAYS, le=retention.MAX_RETENTION_DAYS)


def _org(user: Dict[str, Any]) -> str:
    if not user.get("org_id"):
        raise HTTPException(status_code=403, detail="No organisation on this sign-in")
    return str(user["org_id"])


async def _self(user: Dict[str, Any], person: str, what: str) -> tuple:
    """(org id, user id) when `person` is the caller; 403 (and a ledger entry) for anyone else, whatever the role."""
    uid, org_id = _uid(user), _org(user)
    if person not in ("me", uid):
        await audit_chain.append(actor=uid, action="prime.data.refuse", payload={
            "org_id": org_id, "user_id": person[:255], "what": what, "role": user.get("role")})
        raise HTTPException(status_code=403, detail="Learned data is visible to that person alone")
    return org_id, uid


@router.get("/prime/data/{person}")
async def my_data(person: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """The notice, your switches (with the date each was turned on), and what Prime has learned (counts, newest)."""
    org_id, uid = await _self(user, person, "view")
    return {**await consent.state(org_id, uid), **await learned.summary(org_id, uid),
            "retention_days": await retention.retention_days(org_id)}


@router.put("/prime/data/{person}/consent")
async def set_consent(person: str, body: ConsentIn,
                      user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Turn one source (or the overall switch) on or off. Off stops collection now and deletes what it learned."""
    org_id, uid = await _self(user, person, "consent")
    try:
        withdrawn = await consent.set_switch(org_id, uid, body.source, body.enabled, uid, body.notice_version)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    erased = await learned.withdraw(org_id, uid, withdrawn)
    return {**await consent.state(org_id, uid), "erased": erased}


@router.get("/prime/data/{person}/export")
async def export_data(person: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Everything Prime learned about you, and your consent record, as JSON."""
    org_id, uid = await _self(user, person, "export")
    return await learned.export(org_id, uid)


@router.delete("/prime/data/{person}/learned")
async def erase_data(person: str, source: Optional[Source] = Query(default=None),
                     user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Erase what Prime learned from one source, or from every source when none is given. Consent is unchanged."""
    org_id, uid = await _self(user, person, "erase")
    return {"erased": await learned.erase(org_id, uid, uid, source), "source": source or "all"}


@router.get("/prime/data-retention")
async def get_retention(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, int]:
    """How long this organisation keeps learned data, and the bounds."""
    return {"retention_days": await retention.retention_days(_org(user)),
            "min_days": retention.MIN_RETENTION_DAYS, "max_days": retention.MAX_RETENTION_DAYS}


@router.put("/prime/data-retention")
async def put_retention(body: RetentionIn, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, int]:
    """Change how long learned data is kept. Organisation owner or admin; ledgered."""
    uid, org_id = _uid(user), _org(user)
    if user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only an organisation owner or admin can change retention")
    return {"retention_days": await retention.set_retention_days(org_id, body.retention_days, uid)}
