"""
AetherOS — Preview session exchange (dashboard origin).

  POST /factory/runs/{run_id}/preview-session

The signed-in dashboard asks for a one-time link into the run's generated app on
the preview origin (core/run_app/preview_token.py has the whole flow). The link
carries a 2-minute, single-use ENTER token bound to this run, org and user, with
the run's own origin (<run-id>.<preview host>) as audience; it is never a platform credential.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from aether_os.core.run_app import preview_token
from aether_os.gateway.api_utils import _get_cors_origins
from aether_os.gateway.dependencies import require_run_user

router = APIRouter(tags=["runs"])


@router.post("/factory/runs/{run_id}/preview-session")
async def create_preview_session(
    run_id: str,
    user: Dict[str, Any] = Depends(require_run_user),  # run must belong to the caller's org
) -> Dict[str, Any]:
    problem = preview_token.config_problem(_get_cors_origins())
    if problem:
        raise HTTPException(status_code=503, detail=f"App preview is not configured: {problem}")
    user_id = user.get("user_id")  # API keys have none: previews are for a signed-in person
    if not user_id:
        raise HTTPException(status_code=403, detail="A signed-in user is required to open a preview")
    try:
        origin = preview_token.run_origin(run_id)  # each run has an origin of its own
    except ValueError:
        raise HTTPException(status_code=422, detail="This run id cannot be previewed")
    token = preview_token.issue(run_id, user["org_id"], user_id, preview_token.ENTER,
                                preview_token.ENTER_TTL_S)
    return {
        "url": f"{origin}/__preview/enter?t={token}",
        "preview_origin": origin,
        "expires_in": preview_token.ENTER_TTL_S,
        "iframe_sandbox": preview_token.IFRAME_SANDBOX,
    }
