from __future__ import annotations
import json
import logging
from fastapi import APIRouter, Request, \
    HTTPException, Header
from fastapi.responses import \
    JSONResponse, RedirectResponse
from typing import Optional
from src.integrations.github_app import (
    verify_webhook_signature,
    parse_webhook_event,
    handle_installation_event,
    list_installations,
    get_installation,
    generate_oauth_state,
    validate_oauth_state,
    get_oauth_authorize_url,
    GITHUB_CLIENT_ID
)
from src.api.auth import verify_session_token
from src.database import get_db
from fastapi import Depends
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/github",
    tags=["github"]
)


@router.post("/webhook")
async def github_webhook(
    request: Request,
    x_github_event: Optional[str] = Header(
        None, alias="X-GitHub-Event"),
    x_hub_signature_256: Optional[str] = \
        Header(
            None,
            alias="X-Hub-Signature-256")
):
    """Receive GitHub App webhook events."""
    body = await request.body()

    if not verify_webhook_signature(
            body, x_hub_signature_256):
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature"
        )

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload"
        )

    event_type = x_github_event or "unknown"
    event = parse_webhook_event(
        event_type, payload)

    if event_type == "installation":
        result = handle_installation_event(
            event)
        return result

    logger.info(
        f"GitHub event: {event_type} / "
        f"{event.action}")
    return {
        "status": "received",
        "event": event_type,
        "action": event.action
    }


@router.get("/installations")
async def get_installations(
    request: Request,
    db: Session = Depends(get_db)
):
    """List GitHub App installations — always reads from DB for persistence across restarts."""
    token = request.cookies.get("session_token")
    if not verify_session_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")

    from src.models import GitHubInstallation
    rows = db.query(GitHubInstallation).filter(
        GitHubInstallation.is_active == True  # noqa: E712
    ).all()

    # Also sync DB state into the in-memory store so other code paths stay consistent
    from src.integrations.github_app import _INSTALLATIONS
    for r in rows:
        iid = str(r.installation_id)
        if iid not in _INSTALLATIONS:
            _INSTALLATIONS[iid] = {
                "installation_id": iid,
                "account_login": r.account_login,
                "account_type": r.account_type,
                "repos": [],
                "is_active": True,
            }

    installations = [
        {
            "installation_id": r.installation_id,
            "account_login": r.account_login,
            "account_type": r.account_type,
            "repos": [],
            "is_active": r.is_active,
        }
        for r in rows
    ]
    return {
        "installations": installations,
        "total": len(installations)
    }


@router.get("/oauth/start")
async def oauth_start(request: Request):
    """Start GitHub OAuth flow."""
    token = request.cookies.get(
        "session_token")
    if not verify_session_token(token):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    if not GITHUB_CLIENT_ID:
        return JSONResponse({
            "error": "GitHub App not configured",
            "configured": False
        })

    state = generate_oauth_state(
        redirect_uri="/dashboard/github"
    )
    url = get_oauth_authorize_url(state)
    return {"url": url, "state": state}


@router.get("/oauth/callback")
async def oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None
):
    """Handle GitHub OAuth callback."""
    if error:
        return RedirectResponse(
            url=f"/dashboard/github"
                f"?error={error}")

    if not state or not \
            validate_oauth_state(state):
        raise HTTPException(
            status_code=400,
            detail="Invalid OAuth state"
        )

    # In production: exchange code for token
    # For now: redirect to dashboard
    return RedirectResponse(
        url="/dashboard/github"
            "?connected=true")


@router.get("/status")
async def github_status(request: Request):
    """GitHub App configuration status."""
    token = request.cookies.get(
        "session_token")
    if not verify_session_token(token):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )
    from src.integrations.github_app import \
        GITHUB_APP_ID, GITHUB_CLIENT_ID
    return {
        "configured": bool(
            GITHUB_APP_ID or GITHUB_CLIENT_ID),
        "installations": len(
            list_installations()),
        "app_id": GITHUB_APP_ID or None
    }
