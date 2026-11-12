"""AetherOS — the gateway's one call into the policy engine.

    await enforce("run.start", user)

Raises the HTTP error for a denial; the body always carries the machine-readable
reason as detail.error (the dashboard already keys on that for trial_limit_reached).
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException

from aether_os.core.policy.enforce import authorize

# Anything not listed is 403.
_STATUS = {
    "trial_limit_reached": 402,
    "quota_runs_per_period": 402,
    "quota_concurrent_runs": 429,
    "policy_unavailable": 503,
}


async def enforce(action: str, user: Dict[str, Any], resource_id: str = "") -> None:
    decision = await authorize(
        action, org_id=user.get("org_id") or "", role=user.get("role") or "",
        actor=user.get("user_id") or user.get("sub") or "-", resource_id=resource_id,
    )
    if decision.allowed:
        return
    status = _STATUS.get(decision.reason, 403)
    detail = {"error": decision.reason, "action": action, **decision.detail}
    if status == 402:
        detail["upgrade_url"] = "/pricing"
    raise HTTPException(status_code=status, detail=detail)
