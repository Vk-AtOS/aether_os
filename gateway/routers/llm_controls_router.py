"""LLM spend and safety controls (KAN-116, D6).

  GET  /admin/llm/status                  superadmin  global kill-switch state
  POST /admin/llm/kill-switch             superadmin  {"on": bool}  stop/resume every model call, all workers
  PUT  /admin/llm/orgs/{org_id}/cap       superadmin  {"monthly_cap_usd": float|null}  override the plan default
  POST /settings/llm/kill-switch          org admin   {"on": bool}  stop/resume model calls for the caller's org
  GET  /settings/llm/usage                org member  spend, cap and percent used this month
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import update

from aether_os.core.db import get_session_factory
from aether_os.core.llm import budget, controls
from aether_os.core.llm.budget import get_budget_manager
from aether_os.core.llm.plans import PLAN_LIMITS
from aether_os.core.models import Organisation
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["llm-controls"])


class KillBody(BaseModel):
    on: bool


class CapBody(BaseModel):
    monthly_cap_usd: Optional[float] = None


def _superadmin(user: Dict[str, Any]) -> None:
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin only")


async def _set_org(org_id: str, **values: Any) -> None:
    async with get_session_factory()() as session:
        res = await session.execute(update(Organisation).where(Organisation.id == org_id).values(**values))
        await session.commit()
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="Organisation not found")
    controls.forget_org(org_id)


async def _ledger(user: Dict[str, Any], action: str, org_id: str, detail: Dict[str, Any]) -> None:
    from aether_os.core.audit.ledger import get_ledger
    await get_ledger().async_log_audit_event(
        org_id=org_id, user_id=str(user.get("user_id", "-")), action=action,
        resource_type="llm_controls", resource_id=org_id, metadata=detail)


@router.get("/admin/llm/status")
async def status(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    _superadmin(user)
    return {"global_kill_switch": await controls.global_kill_active(), "env_kill_switch": controls.env_kill_switch()}


@router.post("/admin/llm/kill-switch")
async def global_kill(body: KillBody, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    _superadmin(user)
    try:
        await controls.set_global_kill(body.on)
    except Exception as exc:
        logger.warning("Global LLM kill switch could not be changed: %s", exc)
        raise HTTPException(status_code=503, detail="Shared store unavailable; kill switch NOT changed") from exc
    await _ledger(user, "llm.kill_switch.global", user.get("org_id", "platform"), {"on": body.on})
    return {"global_kill_switch": body.on}


@router.put("/admin/llm/orgs/{org_id}/cap")
async def set_org_cap(org_id: str, body: CapBody, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    _superadmin(user)
    if body.monthly_cap_usd is not None and body.monthly_cap_usd < 0:
        raise HTTPException(status_code=422, detail="monthly_cap_usd must be >= 0")
    await _set_org(org_id, llm_monthly_cap_usd=body.monthly_cap_usd)
    await _ledger(user, "llm.cap.set", org_id, {"monthly_cap_usd": body.monthly_cap_usd})
    return {"org_id": org_id, "monthly_cap_usd": body.monthly_cap_usd}


@router.post("/settings/llm/kill-switch")
async def org_kill(body: KillBody, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") not in ("owner", "admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    await _set_org(user["org_id"], llm_disabled=body.on)
    await _ledger(user, "llm.kill_switch.org", user["org_id"], {"on": body.on})
    return {"llm_disabled": body.on}


@router.get("/settings/llm/usage")
async def usage(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    policy = await controls.org_policy(user["org_id"])
    if policy is None:
        raise HTTPException(status_code=404, detail="Organisation not found")
    limit = PLAN_LIMITS.get(policy.plan)
    cap = policy.cap_usd if policy.cap_usd is not None else (limit.usd if limit else 0.0)
    u = await get_budget_manager().get_usage(user["org_id"], time.strftime("%Y-%m"))
    spent = u["estimated_cost_usd"] or 0.0
    async with get_session_factory()() as session:
        today = await budget._daily_spent(session, user["org_id"], budget._today())
    return {"plan": policy.plan, "month": time.strftime("%Y-%m"), "spent_usd": round(spent, 4),
            "cap_usd": cap, "percent_used": round(100 * spent / cap, 1) if cap else 100.0,
            "llm_disabled": policy.disabled,
            "today_spent_usd": round(today, 4), "daily_cap_usd": round(budget.daily_cap_usd(cap), 2)}
