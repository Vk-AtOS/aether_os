"""HR proxy: POST /hr/{agent}/{method} -> Velaris POST /agents/{agent}/{method}, for the pairs in
gateway/velaris_hr_table.py and NO others (not a generic passthrough). Rules per row (role, typed confirmation,
timeout, body and answer caps, ledger of names only) live in gateway/velaris_proxy.py. Velaris still applies its
own allow-list and roles, and answers 202 for acts that wait for approval; that is passed through unchanged.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import Depends

from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.velaris_hr_table import HR_ALLOW, HR_DEDICATED, HR_ROUTES  # noqa: F401  (re-exported)
from aether_os.gateway.velaris_proxy import build_router, identity

router = build_router("/hr", "/agents", HR_ROUTES, "velaris-hr")


@router.get("/allowlist")
async def allowlist(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """The pairs this proxy will forward (lets the UI say 'not available' instead of guessing). `admin` lists the
    pairs that need the owner/admin role and `confirm` the typed word a destructive pair needs."""
    await identity(user, acting=False)
    return {"agents": {a: sorted(m) for a, m in sorted(HR_ALLOW.items())},
            "admin": sorted(f"{a}.{m}" for a, m in HR_DEDICATED),
            "confirm": {f"{r.path.strip('/').replace('/', '.')}": r.confirm for r in HR_ROUTES if r.confirm}}
