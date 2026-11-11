"""
AetherOS — App Preview Proxy Router

Proxies /app-preview/* to the generated-app process of ONE run: the run named
in the caller's preview cookie (issued by the authenticated run-app endpoints
after an org check — see run_app_router._grant_preview).  The port is only used
while the process recorded for that run is alive and is the one that was
launched for it (core.run_app.preview_state); a stale record means "app down".
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response

from aether_os.core.run_app import preview_state
from aether_os.core.services.run_app_service import _launch_generated_app
from aether_os.gateway.auth import PREVIEW_COOKIE, decode_access_token, decode_preview_token

router = APIRouter(tags=["app-preview"])
logger = logging.getLogger(__name__)

# Never forwarded to LLM-generated code: platform credentials and hop-by-hop headers.
_DROP_REQUEST_HEADERS = {
    "host", "content-length", "cookie",
    "x-org-id", "x-metrics-key", "x-portal-token", "x-api-key",
}
_RUN_ID_PREFIX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/?/?"
)


def _page(message: str, status_code: int, refresh: bool = False) -> Response:
    meta = '<meta http-equiv="refresh" content="4">' if refresh else ""
    return Response(
        content=(
            '<!DOCTYPE html><html><head><meta charset="utf-8"><title>AetherOS — App Preview</title>'
            f"{meta}<style>body{{font-family:system-ui,sans-serif;background:#0f172a;color:#94a3b8;"
            "display:flex;align-items:center;justify-content:center;height:100vh;margin:0;"
            f"font-size:14px;text-align:center}}</style></head><body><p>{message}</p></body></html>"
        ),
        status_code=status_code,
        media_type="text/html",
    )


def _is_platform_credential(value: str) -> bool:
    """True for an Authorization value that is a platform JWT or API key.

    The generated app has its own login, so its own bearer tokens must pass
    through — but a platform token must never reach generated code.
    """
    token = value[7:] if value.lower().startswith("bearer ") else value
    return token.startswith("aesk_") or decode_access_token(token) is not None


def _forward_headers(request: Request) -> dict:
    return {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _DROP_REQUEST_HEADERS
        and not (k.lower() == "authorization" and _is_platform_credential(v))
    }


def _restart_page(run_id: str, org_id: str) -> Response:
    """App is down — restart it as the cookie's org (the launcher re-checks run ownership)."""
    try:
        restart_user = {"org_id": org_id, "user_id": "system", "role": "admin"}
        asyncio.create_task(_launch_generated_app(run_id=run_id, user=restart_user))
        logger.info("app-preview: auto-restarting run %s (app down)", run_id)
    except Exception as exc:
        logger.warning("app-preview: auto-restart failed for run %s: %s", run_id, exc)
        return _page("Generated app is not running.", 503)
    return _page("Starting generated app… page will refresh automatically.", 200, refresh=True)


@router.api_route("/app-preview", methods=["GET", "HEAD"], include_in_schema=False)
@router.api_route(
    "/app-preview/{path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def _app_preview_proxy(request: Request, path: str = "") -> Response:
    """Reverse-proxy requests to the caller's running generated app."""
    # Auth: signed, run-scoped cookie (an iframe cannot send a bearer header).
    claims = decode_preview_token(request.cookies.get(PREVIEW_COOKIE, ""))
    if not claims:
        return _page(
            "Preview session missing or expired.<br><small>Open your project and click "
            "<strong>Run App</strong>.</small>",
            401,
        )
    run_id, org_id = claims["run_id"], claims["org_id"]

    # run_id comes from the signed cookie, so the state path is not caller-controlled.
    port = await asyncio.to_thread(preview_state.live_port, run_id)
    if port is None:
        if preview_state.was_launched(run_id):
            # Dead process or stale record (reused pid/port): never proxy to it.
            return _restart_page(run_id, org_id)
        return _page(
            "No generated app is currently running.<br><small>Go to your project and click "
            "<strong>Run App</strong> to start one.</small>",
            503,
        )

    qs = f"?{request.url.query}" if request.url.query else ""
    # Strip run_id UUID prefix from path so /app-preview/{run_id}/health → /health
    target = f"http://127.0.0.1:{port}/{_RUN_ID_PREFIX.sub('', path)}{qs}"

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            upstream = await client.request(
                method=request.method,
                url=target,
                headers=_forward_headers(request),
                content=await request.body(),
            )
        skip = {"transfer-encoding", "content-encoding", "content-security-policy", "x-frame-options",
                preview_state.NONCE_HEADER}
        headers = {k: v for k, v in upstream.headers.items() if k.lower() not in skip}
        # Generated Vite apps have no nonces — allow scripts/styles/eval so the app renders
        headers["content-security-policy"] = "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:;"
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=headers,
            media_type=upstream.headers.get("content-type"),
        )

    except httpx.ConnectError:
        return _restart_page(run_id, org_id)

    except Exception as exc:
        logger.warning("app_preview_router: preview proxy error: %s", exc)
        return Response(content="Preview proxy error", status_code=502, media_type="text/plain")
