"""
HMAC and token verification for CI webhooks.
"""

from __future__ import annotations

import hashlib
import hmac


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
