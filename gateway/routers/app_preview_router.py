"""
AetherOS — App Preview Proxy Router

Proxies /app-preview/* to the ephemeral port of the most-recently started
generated-app process.  Port state lives in api._APP_PORTS / api._APP_CURRENT_RUN
so it is shared with factory_runs_router without duplication.
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter(tags=["app-preview"])
logger = logging.getLogger(__name__)


@router.api_route("/app-preview", methods=["GET", "HEAD"], include_in_schema=False)
@router.api_route(
    "/app-preview/{path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
async def _app_preview_proxy(request: Request, path: str = "") -> Response:
    """Reverse-proxy requests to the running generated app."""
    import httpx as _httpx
    from aether_os.gateway import api as _api

    # Resolve port: in-process cache first, then Redis (multi-worker safe)
    _port = int(os.environ.get("RUN_APP_PORT", "8001"))
    if _api._APP_CURRENT_RUN:
        _port = _api._APP_PORTS.get(_api._APP_CURRENT_RUN[0], _port)
    else:
        try:
            from aether_os.core.rate_limiter import run_app_port_get as _rapg
            _rid, _rport = await _rapg()
            if _rport:
                _port = _rport
                _api._APP_PORTS[_rid] = _rport
                if not _api._APP_CURRENT_RUN:
                    _api._APP_CURRENT_RUN.append(_rid)
                else:
                    _api._APP_CURRENT_RUN[0] = _rid
        except Exception:
            pass

    _qs = f"?{request.url.query}" if request.url.query else ""
    _target = f"http://127.0.0.1:{_port}/{path}{_qs}"

    try:
        async with _httpx.AsyncClient(timeout=30.0, follow_redirects=True) as _c:
            _r = await _c.request(
                method=request.method,
                url=_target,
                headers={
                    k: v
                    for k, v in request.headers.items()
                    if k.lower() not in ("host", "content-length")
                },
                content=await request.body(),
            )
        _skip = {"transfer-encoding", "content-encoding", "content-security-policy", "x-frame-options"}
        _headers = {k: v for k, v in _r.headers.items() if k.lower() not in _skip}
        # Generated Vite apps have no nonces — allow scripts/styles/eval so the app renders
        _headers["content-security-policy"] = "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:;"
        return Response(
            content=_r.content,
            status_code=_r.status_code,
            headers=_headers,
            media_type=_r.headers.get("content-type"),
        )

    except _httpx.ConnectError:
        # App is down — try to auto-restart if we have a run_id
        _restart_triggered = False
        if _api._APP_CURRENT_RUN:
            _dead_run = _api._APP_CURRENT_RUN[0]
            try:
                from aether_os.gateway.routers.factory_runs_router import start_run_app as _sar
                _system_user = {"org_id": None, "user_id": "system", "role": "admin"}
                asyncio.create_task(_sar(run_id=_dead_run, user=_system_user))
                _restart_triggered = True
                logger.info("app-preview: auto-restarting run %s after ConnectError", _dead_run)
            except Exception as _re:
                logger.debug("app-preview: auto-restart failed: %s", _re)

        _html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>AetherOS — Starting App…</title>
<style>
  body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;flex-direction:column;gap:16px}}
  .spinner{{width:40px;height:40px;border:3px solid rgba(99,102,241,.3);border-top-color:#6366f1;border-radius:50%;animation:spin 0.8s linear infinite}}
  @keyframes spin{{to{{transform:rotate(360deg)}}}}
  p{{color:#94a3b8;font-size:14px;text-align:center}}
  small{{color:#475569;font-size:12px}}
</style>
{'<meta http-equiv="refresh" content="4">' if _restart_triggered else ''}
</head><body>
<div class="spinner"></div>
<p>{'Starting generated app… page will refresh automatically.' if _restart_triggered else 'Generated app is not running.'}<br>
{'<small>This takes ~10–20 seconds on first start.</small>' if _restart_triggered else '<small>Go to the project view and click <strong>Run App</strong>.</small>'}</p>
</body></html>"""
        return Response(
            content=_html,
            status_code=200 if _restart_triggered else 503,
            media_type="text/html",
        )

    except Exception as _pe:
        return Response(
            content=f"Preview proxy error: {_pe}",
            status_code=502,
            media_type="text/plain",
        )
