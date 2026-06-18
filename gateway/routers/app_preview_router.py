"""
AetherOS — App Preview Proxy Router

Proxies /app-preview/* to the ephemeral port of the most-recently started
generated-app process.  Port state is read from core.app_state (Redis-backed,
shared across workers and gateway restarts).
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
    from aether_os.core.app_state import (
        get_current_run_id as _gcr,
        get_all_ports as _gap,
        get_app_state as _gas,
    )

    # Resolve port: in-process cache first, then Redis, then disk state files
    _port = None
    _current_rid = await _gcr()
    if _current_rid:
        _cached_port = _gap().get(_current_rid)
        if _cached_port:
            _port = _cached_port
        else:
            # Cross-worker: fetch full state from Redis
            try:
                _state = await _gas(_current_rid)
                if _state and _state.get("port"):
                    _port = _state["port"]
            except Exception as exc:
                logger.debug("Failed to fetch app state from Redis for run %s: %s", _current_rid, exc)

    # Fallback: scan run_app_state.json files on disk (handles gateway restarts
    # and multi-worker deployments where only one worker ran auto-restore)
    if _port is None:
        import glob as _g, json as _j, socket as _sk
        from pathlib import Path as _Pth
        from aether_os.core.app_state import set_app_state as _sas_fb, set_current_run_id as _scr_fb
        _state_files = sorted(
            _g.glob(str(_Pth.home() / ".aether_os" / "projects" / "*" / "run_app_state.json")),
            key=lambda p: _Pth(p).stat().st_mtime,
            reverse=True,
        )
        for _sf in _state_files:
            try:
                _st = _j.loads(_Pth(_sf).read_text())
                # run_id may be omitted if the state file was written manually;
                # fall back to the parent directory name (project dir == run_id)
                _rid = _st.get("run_id") or _Pth(_sf).parent.name
                _rport = int(_st.get("port", 0))
                if not _rid or not _rport:
                    continue
                _alive = False
                try:
                    with _sk.create_connection(("127.0.0.1", _rport), timeout=0.5):
                        _alive = True
                except OSError:
                    pass
                if _alive:
                    _port = _rport
                    _current_rid = _rid
                    # Register in Redis + memory so subsequent requests in any worker hit cache
                    try:
                        await _sas_fb(_rid, port=_rport, pid=_st.get("pid", 0),
                                      mode=_st.get("mode", "backend"),
                                      app_dir=str(_Pth(_sf).parent))
                        await _scr_fb(_rid)
                    except Exception as exc:
                        logger.debug("Failed to register app state from disk for run %s: %s", _rid, exc)
                    logger.info("app-preview: resolved port %d for run %s from disk", _rport, _rid)
                    break
            except Exception as exc:
                logger.debug("Failed to parse run_app_state.json at %s: %s", _sf, exc)
                continue

    if _port is None:
        return Response(
            content="""<!DOCTYPE html><html><head><meta charset="utf-8"><title>AetherOS — No App Running</title>
<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;flex-direction:column;gap:12px}
p{color:#94a3b8;font-size:14px;text-align:center}a{color:#6366f1}</style>
</head><body><p>No generated app is currently running.<br><small>Go to your project and click <strong>Run App</strong> to start one.</small></p></body></html>""",
            status_code=503,
            media_type="text/html",
        )

    _qs = f"?{request.url.query}" if request.url.query else ""
    # Strip run_id UUID prefix from path so /app-preview/{run_id}/health → /health
    import re as _re_uuid
    _fwd_path = _re_uuid.sub(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/?/?",
        "", path
    )
    _target = f"http://127.0.0.1:{_port}/{_fwd_path}{_qs}"

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
        if _current_rid:
            _dead_run = _current_rid
            try:
                from aether_os.gateway.routers.run_app_router import start_run_app as _sar
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
