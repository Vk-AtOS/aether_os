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

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])


# ── Auth helper ────────────────────────────────────────────────────────────────

def _current_user():
    return Depends(get_current_user)


# ── Shared state helpers (no import from factory_runs_router) ──────────────────

class _ExternalProcess:
    """Lightweight PID wrapper so recovered processes behave like Popen objects."""

    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):
        try:
            os.kill(self.pid, 0)
            return None  # alive
        except (ProcessLookupError, PermissionError):
            return 1  # dead

    def terminate(self):
        try:
            import signal as _sig
            os.kill(self.pid, _sig.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def kill(self):
        try:
            import signal as _sig
            os.kill(self.pid, _sig.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def wait(self, timeout=None):
        pass


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
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Start the generated app with uvicorn. Installs deps and builds frontend."""
    from aether_os.core.run_app.process_manager import RunAppManager
    org_id = user.get("org_id")
    return await RunAppManager().start(run_id=run_id, org_id=org_id, user=user)


@router.delete("/factory/runs/{run_id}/run-app")
async def stop_run_app(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Kill the background app process for a run."""
    _run_procs = _get_app_procs()
    _run_ports = _get_app_ports()
    proc = _run_procs.get(run_id)
    if proc is None or proc.poll() is not None:
        return {"status": "not_running"}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception as exc:
        logger.debug("Process wait timed out for run %s, sending SIGKILL: %s", run_id, exc)
        proc.kill()
    del _run_procs[run_id]
    _run_ports.pop(run_id, None)
    try:
        from aether_os.core.app_state import clear_app_state as _cas, del_proc as _dp
        _dp(run_id)
        await _cas(run_id)
    except Exception as exc:
        logger.debug("Failed to clear app state after stopping run %s: %s", run_id, exc)
    return {"status": "stopped", "run_id": run_id}


@router.get("/factory/runs/{run_id}/run-app/status")
async def run_app_status(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return whether the generated app is currently running."""
    import json as _json_s
    from aether_os.core.projects import get_project_manager as _gpm_s
    _run_procs = _get_app_procs()
    _run_ports = _get_app_ports()
    proc = _run_procs.get(run_id)
    running = proc is not None and proc.poll() is None
    port = _run_ports.get(run_id, int(os.environ.get("RUN_APP_PORT", "8001")))
    pid = proc.pid if running else None

    if not running:
        try:
            root_dir = _gpm_s().get_project_dir(run_id).resolve()
            state_file = root_dir / "run_app_state.json"
            if state_file.exists():
                _s = _json_s.loads(state_file.read_text())
                _pid = _s.get("pid")
                _port = _s.get("port")
                if _pid and _port:
                    try:
                        os.kill(_pid, 0)
                        running = True
                        port = _port
                        pid = _pid
                        _proc_obj = _ExternalProcess(_pid)
                        _run_procs[run_id] = _proc_obj
                        _run_ports[run_id] = _port
                        # Re-publish to Redis + in-memory state
                        try:
                            from aether_os.core.app_state import (
                                set_app_state as _sas2,
                                set_proc as _sp2,
                            )
                            _sp2(run_id, _proc_obj)
                            await _sas2(
                                run_id,
                                port=_port,
                                pid=_pid,
                                mode=_s.get("mode", "backend"),
                                app_dir=str(root_dir),
                            )
                        except Exception as exc:
                            logger.debug("Failed to re-register app state from disk for run %s: %s", run_id, exc)
                    except (ProcessLookupError, PermissionError):
                        pass
        except Exception as exc:
            logger.debug("Failed to restore run-app state from disk for run %s: %s", run_id, exc)

    return {
        "running": running,
        "port": port,
        "pid": pid,
        "preview_url": "/app-preview/" if running else None,
    }


@router.get("/factory/runs/{run_id}/preview-credentials")
async def get_preview_credentials(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
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
    user: Dict[str, Any] = _current_user(),
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
