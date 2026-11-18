"""AetherOS — the gateway's one call into the policy engine.

    await enforce("run.start", user)

Raises the HTTP error for a denial; the body always carries the machine-readable
reason as detail.error (the dashboard already keys on that for trial_limit_reached).
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException

from aether_os.core.policy.enforce import admit_new_run, authorize

# Anything not listed is 403.
_STATUS = {
    "trial_limit_reached": 402,
    "quota_runs_per_period": 402,
    "quota_concurrent_runs": 429,
    "quota_seats": 402,
    "policy_unavailable": 503,
    "platform_at_capacity": 503,
}


def _caller(user: Dict[str, Any]) -> Dict[str, str]:
    return {"org_id": user.get("org_id") or "", "role": user.get("role") or "",
            "actor": user.get("user_id") or user.get("sub") or "-"}


async def enforce(action: str, user: Dict[str, Any], resource_id: str = "") -> None:
    _raise_if_denied(action, await authorize(action, resource_id=resource_id, **_caller(user)))


async def admit_run_start(user: Dict[str, Any], resource_id: str = "") -> None:
    """Every route that starts a new build calls this: policy check plus the atomic
    trial-allowance consume (402 when the allowance is gone)."""
    _raise_if_denied("run.start", await admit_new_run(resource_id=resource_id, **_caller(user)))


def _raise_if_denied(action: str, decision: Any) -> None:
    if decision.allowed:
        return
    status = _STATUS.get(decision.reason, 403)
    detail = {"error": decision.reason, "action": action, **decision.detail}
    if status == 402:
        detail["upgrade_url"] = "/pricing"
    raise HTTPException(status_code=status, detail=detail)


async def enforce_seat(org_id: str, actor: str) -> None:
    """Every path that adds an active user to an existing org (invite, SCIM, SAML) calls this.
    402 with detail.error == "quota_seats" when the plan's seats are used."""
    await enforce("user.add", {"org_id": org_id, "role": "admin", "sub": actor})
