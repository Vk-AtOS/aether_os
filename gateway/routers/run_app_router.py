"""
AetherOS — Run-App Router
=========================
Handles everything related to starting, stopping, and proxying to a generated
application preview process.

Routes
------
  POST   /factory/runs/{run_id}/run-app
  DELETE /factory/runs/{run_id}/run-app
  GET    /factory/runs/{run_id}/run-app/status
  GET    /factory/runs/{run_id}/preview-credentials
  GET    /factory/runs/{run_id}/preview          (SPA proxy — static index.html)

Independently importable — no imports from factory_runs_router.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse

from aether_os.core.app_state import clear_app_state, del_proc
from aether_os.core.run_app import preview_state
from aether_os.core.sandbox.docker_backend import remove_container
from aether_os.gateway.auth import PREVIEW_COOKIE, create_preview_token

from aether_os.gateway.dependencies import get_current_user, require_run_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])


# ── Auth helper ────────────────────────────────────────────────────────────────

def _current_user():
    return Depends(get_current_user)


def _grant_preview(response: Response, run_id: str, user: Dict[str, Any]) -> None:
    """Set the HttpOnly cookie that lets this browser open /app-preview for this run.

    Only reached after require_run_user, so the run belongs to the caller's org.
    HttpOnly + Path=/app-preview: generated-app JS cannot read it and it is not
    sent to the platform API.
    """
    response.set_cookie(
        PREVIEW_COOKIE,
        create_preview_token(run_id, user["org_id"]),
        max_age=8 * 3600,
        path="/app-preview",
        httponly=True,
        samesite="lax",
        secure=os.environ.get("FRONTEND_URL", "").startswith("https://"),
    )


# ── Shared state helpers (no import from factory_runs_router) ──────────────────

def _get_app_procs() -> Dict[str, Any]:
    from aether_os.core.app_state import get_all_procs
    return get_all_procs()


def _get_app_ports() -> Dict[str, int]:
    from aether_os.core.app_state import get_all_ports
    return get_all_ports()


async def acquire_free_port() -> int:
    from aether_os.core.services.run_app_service import acquire_free_port as _afp
    return await _afp()


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/factory/runs/{run_id}/run-app")
async def start_run_app(
    run_id: str,
    response: Response = None,  # None when called in-process (lifespan auto-restore, deploy)
    user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, Any]:
    """Start the generated app with uvicorn. Installs deps and builds frontend."""
    from aether_os.core.services.run_app_service import _launch_generated_app
    result = await _launch_generated_app(run_id=run_id, user=user)
    if response is not None:
        _grant_preview(response, run_id, user)
    return result


@router.delete("/factory/runs/{run_id}/run-app")
async def stop_run_app(
    run_id: str,
    user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, Any]:
    """Kill the background app process for a run."""
    # Only a process proven to be this run's launch (own child handle, or pid +
    # nonce) is ever signalled: a pid taken from a stale state file may by now
    # belong to anything.
    app = await asyncio.to_thread(preview_state.live_app, run_id)
    if app is None:
        return {"status": "not_running"}
    proc = _get_app_procs().get(run_id)
    if proc is not None and proc.poll() is None:  # a handle this process holds
        proc.terminate()
        try:
            await asyncio.to_thread(proc.wait, 5)
        except subprocess.TimeoutExpired:
            logger.warning("run-app %s did not stop on SIGTERM, sending SIGKILL", run_id)
            proc.kill()
    elif app.get("container"):  # Docker sandbox, earlier gateway process; proven by container id + nonce
        await asyncio.to_thread(remove_container, app["container"])
    elif app["pid"]:  # started by an earlier gateway process; identity proven by pid + nonce
        try:
            os.kill(app["pid"], signal.SIGTERM)
        except OSError as exc:
            logger.warning("Could not signal run-app pid %s for run %s: %s", app["pid"], run_id, exc)
    _get_app_ports().pop(run_id, None)
    try:
        del_proc(run_id)
        await clear_app_state(run_id)
    except Exception as exc:
        logger.warning("Failed to clear app state after stopping run %s: %s", run_id, exc)
    return {"status": "stopped", "run_id": run_id}


@router.get("/factory/runs/{run_id}/run-app/status")
async def run_app_status(
    run_id: str,
    response: Response,
    user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, Any]:
    """Return whether the generated app is currently running.

    "Running" means what it means to the preview proxy: the process launched for
    this run is alive (preview_state.live_app). The state file alone is never
    believed — it used to be, so a stale file whose pid had been reused showed
    another process as this run's app.
    """
    app = await asyncio.to_thread(preview_state.live_app, run_id)
    if app is None:
        return {"running": False, "port": None, "pid": None, "preview_url": None}
    _grant_preview(response, run_id, user)
    return {"running": True, "port": app["port"], "pid": app["pid"], "preview_url": "/app-preview/"}


@router.get("/factory/runs/{run_id}/preview-credentials")
async def get_preview_credentials(
    run_id: str,
    user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, Any]:
    """Return demo login credentials for the generated app preview."""
    import json as _json
    import re as _re
    from aether_os.core.projects import get_project_manager
    from aether_os.core.db import get_session_factory as _gsf_pc
    from aether_os.core.models import PhaseCompletion as _PC_pc

    try:
        async with _gsf_pc()() as _sess_pc:
            _p11 = await _sess_pc.get(_PC_pc, (run_id, "p11_deployment"))
            _p11_status = _p11.status if _p11 else "pending"
    except Exception as exc:
        logger.debug("Failed to check p11_deployment phase status for run %s: %s", run_id, exc)
        _p11_status = "unknown"

    if _p11_status not in ("passed", "completed"):
        raise HTTPException(
            status_code=503,
            detail={
                "detail": "app_not_deployed_yet",
                "deployment_status": _p11_status,
            },
        )

    root_dir = get_project_manager().get_project_dir(run_id).resolve()
    creds_path = root_dir / "preview_credentials.json"
    if creds_path.exists():
        return _json.loads(creds_path.read_text())

    for seed_candidate in [
        root_dir / "p04_backend" / "backend_codegen" / "src" / "seed.py",
    ]:
        if seed_candidate.exists():
            txt = seed_candidate.read_text()
            _email_m = _re.search(r'email\s*=\s*["\']([^"\']+@[^"\']+)["\']', txt)
            _pass_m = _re.search(r'_ADMIN_PASSWORD\s*=\s*["\']([^"\']+)["\']', txt)
            if _email_m or _pass_m:
                return {
                    "email": _email_m.group(1) if _email_m else "admin@example.com",
                    "password": _pass_m.group(1) if _pass_m else "(check seed.py)",
                    "note": "Extracted from seed.py — run 'Run App' to get predictable credentials",
                }

    raise HTTPException(
        status_code=503,
        detail={
            "detail": "app_not_running",
            "reason": "container_crashed",
            "suggestion": "Check deployment logs for the error cause",
        },
    )


@router.get("/factory/runs/{run_id}/preview")
async def preview_run_html(
    run_id: str,
    user: Dict[str, Any] = Depends(require_run_user),
):
    """Serve the generated index.html for a run."""
    import pathlib
    from aether_os.core.audit.ledger import get_ledger as _get_ledger
    from aether_os.core.projects import get_project_manager as _get_pm

    org_id = user.get("org_id")
    run_detail = await _get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not run_detail:
        raise HTTPException(status_code=404, detail="Run not found")

    project_id = run_detail.get("project_id") or run_id
    root_dir = _get_pm().get_project_dir(project_id)

    for candidate in [
        root_dir / "p05_frontend" / "index.html",
        root_dir / "index.html",
    ]:
        if candidate.exists():
            return HTMLResponse(content=candidate.read_text(encoding="utf-8"))

    for html_file in root_dir.rglob("index.html"):
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))

    raise HTTPException(status_code=404, detail="No index.html found in run artifacts")
