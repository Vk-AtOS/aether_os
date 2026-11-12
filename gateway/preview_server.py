"""AetherOS preview server: the only place generated apps are served, on their own origin.

Run as a separate process on AETHER_PREVIEW_ORIGIN (one worker, see ReplayGuard):

    uvicorn aether_os.gateway.preview_server:create_preview_app --factory --port 8100

Routes (nothing else exists here — no platform API, no dashboard):
  GET  /__preview/enter?t=<enter token>  spend the dashboard-issued token, set the
                                         session cookie, redirect to /app-preview/
  GET  /__preview/health                 liveness for nginx / scripts (public: says "ok")
  *    /app-preview/{path}               proxy to the run named in the session cookie

The proxy targets the port recorded for the run, but only after the app proves
it is that launch: it must answer with the launch's nonce header
(core/run_app/preview_state.NONCE_HEADER), checked by a body-less probe before the
request is forwarded and again on the real response. A rewritten state file or a
reused port therefore never sends a user's request to another process. The
server never starts or restarts apps (it has no database or Docker access): an
app that is down shows "start it from the dashboard".
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Dict

# Importable as `aether_os` however uvicorn is invoked (same as gateway/api.py).
_pkg_root = str(Path(__file__).resolve().parent.parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

import httpx  # noqa: E402
import jwt  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import RedirectResponse, Response  # noqa: E402

from aether_os.core.run_app import preview_state, preview_token  # noqa: E402

logger = logging.getLogger(__name__)

UPSTREAM_HOST = os.environ.get("AETHER_SANDBOX_UPSTREAM_HOST", "127.0.0.1")
_PROBE_PATH = "/__aether_preview_probe"
_DROP_REQUEST_HEADERS = {
    "host", "content-length", "cookie", "connection",
    "x-org-id", "x-metrics-key", "x-portal-token", "x-api-key",
}
_DROP_RESPONSE_HEADERS = {
    "transfer-encoding", "content-encoding", "content-length", "connection",
    "content-security-policy", "x-frame-options", "cross-origin-opener-policy",
    "cross-origin-resource-policy", "referrer-policy", preview_state.NONCE_HEADER,
}


def security_headers() -> Dict[str, str]:
    """Headers on every preview response. Generated Vite apps use inline scripts and eval,
    so scripts stay permissive, but: framed only by the dashboard, fetch/XHR only to itself,
    no opener link back to the dashboard window, nothing readable cross-origin."""
    dashboard = preview_token.dashboard_origin()
    ancestors = dashboard if dashboard else "'none'"
    csp = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; "
           "style-src 'self' 'unsafe-inline' https:; img-src 'self' data: blob: https:; "
           "font-src 'self' data: https:; connect-src 'self'; worker-src 'self' blob:; "
           f"form-action 'self'; base-uri 'self'; object-src 'none'; frame-ancestors {ancestors}")
    return {
        "content-security-policy": csp,
        "cross-origin-opener-policy": "same-origin",
        "cross-origin-resource-policy": "same-origin",
        "referrer-policy": "no-referrer",
        "x-content-type-options": "nosniff",
        "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        "cache-control": "no-store",
    }


def _page(message: str, status_code: int) -> Response:
    body = ('<!DOCTYPE html><html><head><meta charset="utf-8"><title>App preview</title></head>'
            '<body style="font-family:system-ui,sans-serif;background:#0f172a;color:#94a3b8;'
            'display:flex;align-items:center;justify-content:center;height:100vh;margin:0">'
            f"<p>{message}</p></body></html>")
    return Response(body, status_code=status_code, media_type="text/html", headers=security_headers())


def is_platform_credential(value: str) -> bool:
    """Authorization values that look like platform credentials (API key or platform JWT).

    The preview server has no platform keys, so this reads claims unverified: anything
    shaped like a platform token is dropped; the generated app's own tokens pass.
    """
    token = value[7:] if value.lower().startswith("bearer ") else value
    if token.startswith("aesk_"):
        return True
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return False
    return isinstance(claims, dict) and bool({"token_type", "org_id", "purpose"} & set(claims))


def forward_headers(request: Request) -> Dict[str, str]:
    return {k: v for k, v in request.headers.items()
            if k.lower() not in _DROP_REQUEST_HEADERS
            and not (k.lower() == "authorization" and is_platform_credential(v))}


def _rewrite_location(location: str) -> str:
    # The app thinks it lives at "/"; keep its absolute-path redirects under the proxy prefix.
    if location.startswith("/") and not location.startswith("//") and not location.startswith("/app-preview"):
        return "/app-preview" + location
    return location


def create_preview_app() -> FastAPI:
    problem = preview_token.config_problem()
    if problem:
        raise RuntimeError(f"preview server refuses to start: {problem}")
    replay = preview_token.ReplayGuard()
    secure = (preview_token.preview_origin() or "").startswith("https://")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/__preview/health", include_in_schema=False)
    async def health() -> Dict[str, str]:  # public on purpose: liveness only, no data
        return {"status": "ok"}

    @app.get("/__preview/enter", include_in_schema=False)
    async def enter(t: str = "") -> Response:
        claims = preview_token.verify(t, preview_token.ENTER)
        if not claims or not replay.first_use(claims["jti"], claims["exp"]):
            return _page("This preview link is invalid, expired or already used. "
                         "Open the preview again from the dashboard.", 401)
        session = preview_token.issue(claims["run_id"], claims["org_id"], claims["sub"],
                                      preview_token.SESSION, preview_token.SESSION_TTL_S)
        resp = RedirectResponse("/app-preview/", status_code=303, headers=security_headers())
        resp.set_cookie(preview_token.SESSION_COOKIE, session, max_age=preview_token.SESSION_TTL_S,
                        path="/", httponly=True, secure=secure, samesite="lax")
        return resp

    @app.api_route("/app-preview", methods=["GET", "HEAD"], include_in_schema=False)
    @app.api_route("/app-preview/{path:path}", include_in_schema=False,
                   methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy(request: Request, path: str = "") -> Response:
        claims = preview_token.verify(request.cookies.get(preview_token.SESSION_COOKIE, ""),
                                      preview_token.SESSION)
        if not claims:
            return _page("Preview session missing or expired. Open the preview again from the dashboard.", 401)
        # run_id comes from the signed cookie, so the state path is not caller-controlled.
        launch = await asyncio.to_thread(preview_state.read_launch, claims["run_id"])
        if not launch:
            return _page("This app is not running. Start it from the dashboard.", 503)
        base = f"http://{UPSTREAM_HOST}:{launch['port']}"
        nonce = launch["nonce"]
        qs = f"?{request.url.query}" if request.url.query else ""
        try:
            # Redirects are passed to the browser, never followed here (no SSRF via Location).
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
                probe = await client.head(base + _PROBE_PATH)
                if probe.headers.get(preview_state.NONCE_HEADER) != nonce:
                    logger.warning("preview: port %s is not run %s's launch", launch["port"], claims["run_id"])
                    return _page("This app is not running. Start it from the dashboard.", 503)
                upstream = await client.request(request.method, f"{base}/{path}{qs}",
                                                headers=forward_headers(request),
                                                content=await request.body())
        except httpx.HTTPError as exc:
            logger.info("preview: upstream for run %s unreachable: %s", claims["run_id"], exc)
            return _page("This app is not running. Start it from the dashboard.", 503)
        if upstream.headers.get(preview_state.NONCE_HEADER) != nonce:
            return _page("This app is not running. Start it from the dashboard.", 503)

        resp = Response(upstream.content, status_code=upstream.status_code)
        for key, value in upstream.headers.multi_items():
            low = key.lower()
            if low in _DROP_RESPONSE_HEADERS or low.startswith("access-control-"):
                continue
            if low == "set-cookie" and value.lstrip().startswith(preview_token.SESSION_COOKIE + "="):
                continue  # the app may not replace the preview session
            resp.headers.append(key, _rewrite_location(value) if low == "location" else value)
        for key, value in security_headers().items():
            resp.headers[key] = value
        return resp

    return app
