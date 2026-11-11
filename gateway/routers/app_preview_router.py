"""
AetherOS — App Preview Proxy Router

Proxies /app-preview/* to the generated-app process of ONE run: the run named
in the caller's preview cookie (issued by the authenticated run-app endpoints
after an org check — see run_app_router._grant_preview).  Port state is read
from core.app_state (Redis-backed, shared across workers and gateway restarts).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response

from aether_os.core.app_state import get_all_ports, get_app_state
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


async def _resolve_port(run_id: str) -> Optional[int]:
    """Port of this run's app: in-process cache, then Redis, then its state file."""
    port = get_all_ports().get(run_id)
    if port:
        return port
    try:
        state = await get_app_state(run_id)
        if state and state.get("port"):
            return int(state["port"])
    except Exception as exc:
        logger.warning("app-preview: app state lookup failed for run %s: %s", run_id, exc)
    # Gateway restart / other worker: the run's own state file (run_id comes from a
    # signed cookie, so this path is not caller-controlled).
    state_file = Path.home() / ".aether_os" / "projects" / run_id / "run_app_state.json"
    try:
        if state_file.exists():
            return int(json.loads(state_file.read_text()).get("port") or 0) or None
    except Exception as exc:
        logger.warning("app-preview: unreadable state file for run %s: %s", run_id, exc)
    return None


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

    port = await _resolve_port(run_id)
    if port is None:
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
        skip = {"transfer-encoding", "content-encoding", "content-security-policy", "x-frame-options"}
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
        # App is down — restart it as the cookie's org (the launcher re-checks run ownership).
        restarted = False
        try:
            restart_user = {"org_id": org_id, "user_id": "system", "role": "admin"}
            asyncio.create_task(_launch_generated_app(run_id=run_id, user=restart_user))
            restarted = True
            logger.info("app-preview: auto-restarting run %s after ConnectError", run_id)
        except Exception as exc:
            logger.warning("app-preview: auto-restart failed for run %s: %s", run_id, exc)
        if restarted:
            return _page("Starting generated app… page will refresh automatically.", 200, refresh=True)
        return _page("Generated app is not running.", 503)

    except Exception as exc:
        logger.warning("app_preview_router: preview proxy error: %s", exc)
        return Response(content="Preview proxy error", status_code=502, media_type="text/plain")
