"""
AetherOS — Client-portal administration (owning organisation side)

  POST   /factory/runs/{run_id}/portal-tokens             issue a token (shown once)
  GET    /factory/runs/{run_id}/portal-tokens             list tokens (no secrets)
  DELETE /factory/runs/{run_id}/portal-tokens/{token_id}  revoke a token
  GET    /factory/runs/{run_id}/portal-approvals          client approvals recorded for the run

Every route: signed-in user of the org that owns the run (require_run_user, 404
otherwise), then the policy engine for the role. The client-facing routes are in
gateway/client_portal/routes.py.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from aether_os.core.identity import portal_access
from aether_os.gateway.dependencies import require_run_user
from aether_os.gateway.policy_guard import enforce

router = APIRouter(tags=["client-portal-admin"])


class IssuePortalTokenRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = Field(default="", max_length=120)  # who it is for, e.g. the client's name
    expires_in_days: int = Field(default=portal_access.DEFAULT_TTL_DAYS, ge=1, le=portal_access.MAX_TTL_DAYS)


def _actor(user: Dict[str, Any]) -> str:
    return user.get("user_id") or user.get("sub") or "-"


@router.post("/factory/runs/{run_id}/portal-tokens")
async def issue_portal_token(
    run_id: str,
    req: Optional[IssuePortalTokenRequest] = None,
    user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, Any]:
    """Issue a portal token for this run. The `token` field is returned here and never again."""
    await enforce("portal.token.issue", user, run_id)
    req = req or IssuePortalTokenRequest()
    view, token = await portal_access.issue_token(
        user["org_id"], run_id, _actor(user), label=req.label, ttl_days=req.expires_in_days)
    return {**view, "token": token}


@router.get("/factory/runs/{run_id}/portal-tokens")
async def list_portal_tokens(run_id: str, user: Dict[str, Any] = Depends(require_run_user)) -> Dict[str, Any]:
    await enforce("portal.token.list", user, run_id)
    return {"tokens": await portal_access.list_tokens(user["org_id"], run_id)}


@router.delete("/factory/runs/{run_id}/portal-tokens/{token_id}")
async def revoke_portal_token(
    run_id: str, token_id: str, user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, Any]:
    await enforce("portal.token.revoke", user, run_id)
    view = await portal_access.revoke_token(user["org_id"], run_id, token_id, _actor(user))
    if view is None:
        raise HTTPException(status_code=404, detail="Portal token not found")
    return view


@router.get("/factory/runs/{run_id}/portal-approvals")
async def list_portal_approvals(run_id: str, user: Dict[str, Any] = Depends(require_run_user)) -> Dict[str, Any]:
    await enforce("portal.approval.list", user, run_id)
    return {"approvals": await portal_access.list_approvals(user["org_id"], run_id)}
