"""
AetherOS — API Gateway Helpers
================================
Pydantic request/response models and middleware classes extracted from
gateway/api.py to keep it under 600 lines.

Exported:
    Pydantic models: PipelineStartRequest, PipelineStartResponse,
                     ApproveRequest, ApiKeyRequest, TestProviderRequest,
                     PhaseConfigUpdate, PriorityRequest, RerunRequest,
                     FileWriteBody, EnvVarItem, EnvVarsBody,
                     SamlConfigRequest, WorkspaceCreate, WorkspaceUpdate
    Middleware:      OrgIDLoggingMiddleware, SecurityHeadersMiddleware,
                     HttpsRedirectMiddleware
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware


# ── Pydantic models ────────────────────────────────────────────────────────────

class PipelineStartRequest(BaseModel):
    requirement: str
    project_name: str = "untitled"
    language: str = "python"
    output_dir: Optional[str] = None
    max_retries: int = 3


class PipelineStartResponse(BaseModel):
    run_id: str
    status: str
    message: str


class ApproveRequest(BaseModel):
    ticket_id: str
    decision: str  # "approve" | "deny"
    reason: Optional[str] = None


class ApiKeyRequest(BaseModel):
    provider: str
    key: str


class TestProviderRequest(BaseModel):
    provider: str


class PhaseConfigUpdate(BaseModel):
    enabled: bool
    priority: str


class PriorityRequest(BaseModel):
    priority: str  # "high" | "normal" | "low"


class RerunRequest(BaseModel):
    from_phase: str


class FileWriteBody(BaseModel):
    path: str
    content: str


class EnvVarItem(BaseModel):
    key: str
    value: str


class EnvVarsBody(BaseModel):
    vars: List[EnvVarItem]


class SamlConfigRequest(BaseModel):
    idp_entity_id: str
    idp_sso_url: str
    idp_cert: str


class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_shared: bool = False
    preferences: Optional[Dict[str, Any]] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_shared: Optional[bool] = None
    preferences: Optional[Dict[str, Any]] = None


# ── Middleware ─────────────────────────────────────────────────────────────────

class OrgIDLoggingMiddleware(BaseHTTPMiddleware):
    """Bind org_id and user_id to structlog context for every request."""

    async def dispatch(self, request: Request, call_next):
        import structlog
        from aether_os.gateway.auth import decode_access_token

        org_id = request.headers.get("X-Org-ID")
        user_id = None

        if not org_id:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                payload = decode_access_token(token)
                if payload:
                    org_id = payload.get("org_id")
                    user_id = payload.get("user_id")

        if org_id:
            structlog.contextvars.bind_contextvars(org_id=org_id)
        if user_id:
            structlog.contextvars.bind_contextvars(user_id=user_id)

        try:
            response = await call_next(request)
            return response
        finally:
            structlog.contextvars.clear_contextvars()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach security headers (CSP, HSTS, X-Frame-Options, etc.) to every response."""

    async def dispatch(self, request: Request, call_next):
        import secrets as _sec
        # Generate a per-request nonce to replace unsafe-inline for script-src (M-10)
        nonce = _sec.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)

        # app-preview proxy handles its own permissive CSP — don't overwrite it
        if request.url.path.startswith("/app-preview"):
            return response

        response.headers["X-Content-Type-Options"] = "nosniff"
        # Rate limit headers on factory start and /auth/login routes
        response.headers["X-RateLimit-Factory-Limit"] = os.getenv("MAX_FACTORY_STARTS_PER_MIN", "10")
        response.headers["X-RateLimit-Hourly-Limit"] = os.getenv("MAX_STARTS_PER_ORG_PER_HOUR", "20")
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # Build frame-src dynamically from CORS_ORIGINS so app preview iframes
        # work in any deployment without hardcoding IPs.
        from urllib.parse import urlparse as _urlparse
        _cors_hosts = " ".join(
            f"{_urlparse(o.strip()).scheme}://{_urlparse(o.strip()).hostname}:*"
            for o in os.getenv("CORS_ORIGINS", "").split(",")
            if o.strip() and not o.strip().startswith("http://localhost")
            and _urlparse(o.strip()).hostname
        )
        _frame_src = f"'self' {_cors_hosts} http://localhost:*".strip()
        # Nonce replaces unsafe-inline for script-src; unsafe-eval kept for Monaco editor.
        # style-src retains unsafe-inline (CSS injection risk lower than script injection).
        # Landing page (/) uses plain 'self' — no strict-dynamic needed, and it blocks external .js
        _is_landing = request.url.path in ("/", "/js/landing.js")
        _script_src = (
            "script-src 'self'; "
            if _is_landing
            else f"script-src 'self' 'nonce-{nonce}' 'strict-dynamic' 'unsafe-eval' https://cdn.jsdelivr.net; "
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            + _script_src
            + "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' https://cdn.jsdelivr.net; "
            "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            f"frame-src {_frame_src}; "
            "worker-src 'self' blob: https://cdn.jsdelivr.net; "
            "frame-ancestors 'none'"
        )
        # B11: HSTS only in production — prevents breaking local dev over HTTP
        if os.getenv("ENVIRONMENT") == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class HttpsRedirectMiddleware(BaseHTTPMiddleware):
    """Redirect HTTP to HTTPS when FORCE_HTTPS=true."""

    async def dispatch(self, request: Request, call_next):
        if os.environ.get("FORCE_HTTPS", "false").lower() == "true":
            proto = request.headers.get("X-Forwarded-Proto")
            if proto == "http":
                url = str(request.url).replace("http://", "https://", 1)
                return RedirectResponse(url=url, status_code=301)
        return await call_next(request)
