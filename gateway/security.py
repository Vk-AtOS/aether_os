"""
HMAC and token verification for CI webhooks.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import HTTPException, Request


def verify_github_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """Verifies HMAC-SHA256 signature from GitHub."""
    if not signature_header or not secret or not signature_header.startswith("sha256="):
        return False

    try:
        expected_sig = signature_header.split("sha256=")[1]
        actual_sig = hmac.new(
            secret.encode("utf-8"),
            payload_body,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(actual_sig, expected_sig)
    except (IndexError, Exception):
        return False


def verify_gitlab_token(token_header: str, secret: str) -> bool:
    """Verifies plain token from GitLab."""
    if not token_header or not secret:
        return False
    
    return hmac.compare_digest(token_header, secret)


def verify_jenkins_token(token_param: str, secret: str) -> bool:
    """Verifies plain token from Jenkins (query param)."""
    if not token_param or not secret:
        return False
    
    return hmac.compare_digest(token_param, secret)


async def require_ci_auth(request: Request) -> None:
    """Router dependency for /ci/*: the caller must hold CI_WEBHOOK_SECRET.

    Accepts a GitHub-style HMAC of the body (X-Hub-Signature-256) or the secret
    itself in X-Gitlab-Token (also the way to call the body-less GET /ci/jobs).
    Fails closed with 503 when the secret is unset — these endpoints queue LLM
    repair jobs and read arbitrary repo paths, so "open by default" is not an option.
    """
    secret = os.environ.get("CI_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="CI webhook is disabled: CI_WEBHOOK_SECRET is not set")
    if verify_gitlab_token(request.headers.get("X-Gitlab-Token", ""), secret):
        return
    if verify_github_signature(await request.body(), request.headers.get("X-Hub-Signature-256", ""), secret):
        return
    raise HTTPException(status_code=401, detail="Invalid CI webhook signature")
