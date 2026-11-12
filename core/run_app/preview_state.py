"""Which process is serving a run's preview, and is it still that process?

`run_app_state.json` used to hold only a port. Ports are reused, so a stale file
could send one run's preview traffic to another run's app. The launcher now
starts the app with a per-launch random nonce on its command line and records
(pid, nonce, port); the preview proxy only uses the port while that pid is alive
and still carries that nonce. Anything else is "app down".

Docker-sandboxed apps have no host pid we own: the record holds the container
id instead, and the container must be running and carry the nonce as a label.
The preview server (a separate process, no Docker access) checks the nonce a
third way: the app must answer with it in its response header (gateway/preview_server.py).
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.core.app_state import get_all_ports, get_all_procs
from aether_os.core.projects import get_project_manager
from aether_os.core.sandbox.docker_backend import ContainerProcess, is_launched_container

logger = logging.getLogger(__name__)

STATE_FILE = "run_app_state.json"
# uvicorn adds this as a default response header; its presence on the command
# line is what ties a pid to one launch. The proxy strips it from responses.
NONCE_HEADER = "x-aether-preview-nonce"


def new_nonce() -> str:
    return secrets.token_hex(16)


def nonce_args(nonce: str) -> List[str]:
    """uvicorn arguments that mark the process as this launch."""
    return ["--header", f"{NONCE_HEADER}:{nonce}"]


def state_path(run_id: str) -> Path:
    # Same root the launcher writes under (get_project_dir), without creating the directory.
    return get_project_manager()._root / run_id / STATE_FILE


def write_state(path: Path, run_id: str, port: int, pid: Optional[int], nonce: str, mode: str,
                container: Optional[str] = None) -> None:
    path.write_text(json.dumps({
        "run_id": run_id, "port": port, "pid": pid, "nonce": nonce,
        "started_at": time.time(), "mode": mode, "container": container,
    }))


def _read_state(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text()) if path.exists() else None
    except Exception as exc:
        logger.warning("preview_state: unreadable state file %s: %s", path, exc)
        return {}  # a file exists but cannot be trusted: stale, not "never launched"


def _command_line(pid: int) -> str:
    proc_file = Path(f"/proc/{pid}/cmdline")
    try:
        if proc_file.exists():  # Linux
            return proc_file.read_bytes().replace(b"\0", b" ").decode(errors="replace")
        return subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)],
                              capture_output=True, text=True, timeout=5).stdout
    except Exception as exc:
        logger.warning("preview_state: could not read command line of pid %s: %s", pid, exc)
        return ""


def is_launched_process(pid: Any, nonce: Any) -> bool:
    """True only if `pid` is alive and is the process started with `nonce`."""
    if not isinstance(pid, int) or pid <= 0 or not isinstance(nonce, str) or len(nonce) < 16:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False  # gone, or a reused pid owned by someone else
    return f"{NONCE_HEADER}:{nonce}" in _command_line(pid)


def live_app(run_id: str, path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """{"port", "pid", "mode", "container"} of this run's launched app, or None when it is not (provably) up.

    The one answer to "is this run's app running?" — the preview proxy, the
    status endpoint, stop, and the restore at startup all ask here, so none of
    them can be led to another run's app by a stale state file.

    Blocking (may run `ps`): call through asyncio.to_thread from request handlers.
    """
    proc = get_all_procs().get(run_id)
    port = get_all_ports().get(run_id)
    if isinstance(proc, (subprocess.Popen, ContainerProcess)):
        # Our own child / container: the handle identifies the process exactly.
        container = getattr(proc, "container_id", None)
        return ({"port": port, "pid": proc.pid, "mode": None, "container": container}
                if port and proc.poll() is None else None)
    state = _read_state(path or state_path(run_id))
    if state is not None:
        nonce, container = state.get("nonce"), state.get("container")
        launched = (is_launched_container(container, nonce) if container
                    else is_launched_process(state.get("pid"), nonce))
        if launched and int(state.get("port") or 0):
            return {"port": int(state["port"]), "pid": state.get("pid"), "mode": state.get("mode"),
                    "container": container}
        return None
    # No state file was ever written, so nothing can be stale: accept an
    # in-process registration that still has a live handle.
    if proc is not None and port and proc.poll() is None:
        return {"port": port, "pid": getattr(proc, "pid", None), "mode": None, "container": None}
    return None


def live_port(run_id: str, path: Optional[Path] = None) -> Optional[int]:
    """Port of the app launched for this run, or None when it is not (provably) up. Blocking, as live_app."""
    app = live_app(run_id, path)
    return app["port"] if app else None


def was_launched(run_id: str) -> bool:
    """An app was started for this run at some point (it may be down now)."""
    return run_id in get_all_procs() or state_path(run_id).exists()


def read_launch(run_id: str) -> Optional[Dict[str, Any]]:
    """{"port", "nonce"} of this run's launch for the preview server, or None.

    The preview server is a separate process without the gateway's child handles
    or Docker access. A host-process launch is checked here (pid alive and
    carrying the nonce); a container launch cannot be, so the caller must also
    see the nonce in the app's own response header before trusting the port.
    Blocking (may run `ps`).
    """
    state = _read_state(state_path(run_id))
    if not state:
        return None
    port, nonce = state.get("port"), state.get("nonce")
    if not isinstance(port, int) or not 0 < port < 65536 or not isinstance(nonce, str) or len(nonce) < 16:
        return None
    if not state.get("container") and not is_launched_process(state.get("pid"), nonce):
        return None
    return {"port": port, "nonce": nonce}
