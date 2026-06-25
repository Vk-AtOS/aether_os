from __future__ import annotations
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

GITHUB_APP_ID = os.getenv(
    "GITHUB_APP_ID", "")
GITHUB_APP_SECRET = os.getenv(
    "GITHUB_WEBHOOK_SECRET", "")
GITHUB_CLIENT_ID = os.getenv(
    "GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv(
    "GITHUB_CLIENT_SECRET", "")

# In-memory store for installations
_INSTALLATIONS: dict[str, dict] = {}
_OAUTH_STATES: dict[str, str] = {}
# {state: redirect_uri}


@dataclass
class GitHubInstallation:
    installation_id: str
    account_login: str
    account_type: str
    # "User" or "Organization"
    repos: list[str] = \
        field(default_factory=list)
    access_token: Optional[str] = None
    is_active: bool = True


@dataclass
class GitHubWebhookEvent:
    event_type: str
    action: Optional[str]
    installation_id: Optional[str]
    repo_full_name: Optional[str]
    sender_login: str
    raw_payload: dict


def verify_webhook_signature(
    payload_bytes: bytes,
    signature_header: Optional[str]
) -> bool:
    """
    Verify GitHub webhook signature.
    Returns True if valid or no secret set.
    """
    if not GITHUB_APP_SECRET:
        return True  # dev mode

    if not signature_header:
        return False

    if not signature_header.startswith(
            "sha256="):
        return False

    expected = hmac.new(
        GITHUB_APP_SECRET.encode(),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()

    received = signature_header[7:]
    return hmac.compare_digest(
        expected, received)


def parse_webhook_event(
    event_type: str,
    payload: dict
) -> GitHubWebhookEvent:
    """Parse a GitHub webhook payload."""
    installation = payload.get(
        "installation", {})
    repo = payload.get("repository", {})

    return GitHubWebhookEvent(
        event_type=event_type,
        action=payload.get("action"),
        installation_id=str(
            installation.get("id", "")
        ) if installation else None,
        repo_full_name=repo.get(
            "full_name"),
        sender_login=payload.get(
            "sender", {}
        ).get("login", "unknown"),
        raw_payload=payload
    )


def handle_installation_event(
    event: GitHubWebhookEvent
) -> dict:
    """
    Handle installation created/deleted events.
    """
    iid = event.installation_id or ""

    if event.action == "created":
        account = event.raw_payload.get(
            "installation", {}
        ).get("account", {})
        repos = [
            r.get("full_name", "")
            for r in event.raw_payload.get(
                "repositories", [])
        ]
        _INSTALLATIONS[iid] = {
            "installation_id": iid,
            "account_login": account.get(
                "login", "unknown"),
            "account_type": account.get(
                "type", "User"),
            "repos": repos,
            "is_active": True
        }
        logger.info(
            f"GitHub App installed: {iid}")
        return {"status": "installed",
                "installation_id": iid}

    elif event.action == "deleted":
        if iid in _INSTALLATIONS:
            _INSTALLATIONS[iid][
                "is_active"] = False
        logger.info(
            f"GitHub App uninstalled: {iid}")
        return {"status": "uninstalled",
                "installation_id": iid}

    return {"status": "ignored",
            "action": event.action}


def get_installation(
    installation_id: str
) -> Optional[dict]:
    return _INSTALLATIONS.get(installation_id)


def list_installations() -> list[dict]:
    return [
        i for i in _INSTALLATIONS.values()
        if i.get("is_active", True)
    ]


def generate_oauth_state(
    redirect_uri: str = ""
) -> str:
    """Generate a random OAuth state."""
    import secrets
    state = secrets.token_urlsafe(32)
    _OAUTH_STATES[state] = redirect_uri
    return state


def validate_oauth_state(
    state: str
) -> bool:
    """Validate and consume OAuth state."""
    if state in _OAUTH_STATES:
        del _OAUTH_STATES[state]
        return True
    return False


def get_oauth_authorize_url(
    state: str
) -> str:
    """Build GitHub OAuth authorization URL."""
    if not GITHUB_CLIENT_ID:
        return ""
    return (
        f"https://github.com/login/oauth/"
        f"authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&state={state}"
        f"&scope=repo"
    )
