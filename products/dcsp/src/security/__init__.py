"""
Security layer for DCSP.
Includes HMAC verification, secret management, and rate limiting.
"""

from __future__ import annotations

from src.security.hmac_verifier import (
    verify_github_signature,
    verify_gitlab_token,
    verify_jenkins_token
)
from src.security.secret_manager import SecretManager, GLOBAL_SECRET_MANAGER
from src.security.rate_limiter import RateLimiter, GLOBAL_RATE_LIMITER

__all__ = [
    "verify_github_signature",
    "verify_gitlab_token",
    "verify_jenkins_token",
    "SecretManager",
    "GLOBAL_SECRET_MANAGER",
    "RateLimiter",
    "GLOBAL_RATE_LIMITER"
]
