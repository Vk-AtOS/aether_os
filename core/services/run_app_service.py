"""
Service layer for launching generated-app subprocesses.

Imported by both:
  - gateway/routers/factory_runs_router.py  (HTTP handler)
  - orchestrator/factory_pipeline.py        (auto-start after pipeline completion)

Keeping the logic here prevents the orchestrator layer from importing the HTTP
router layer (architectural coupling violation [14]).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from aether_os.core.run_app import preview_state

logger = logging.getLogger(__name__)

# Module-level lock prevents two simultaneous calls from grabbing the same port
# (TOCTOU race fix [19]).
_port_lock: Optional[asyncio.Lock] = None


def _get_port_lock() -> asyncio.Lock:
    global _port_lock
    if _port_lock is None:
        _port_lock = asyncio.Lock()
    return _port_lock


def _free_port() -> int:
    """An unused TCP port on localhost from the app range (the preview proxy refuses any other)."""
    import random as _random
    import socket as _sock
    lo, hi = preview_state.port_range()
    ports = list(range(lo, hi + 1))
    _random.shuffle(ports)
    for port in ports[:200]:
        with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"no free port in the app range {lo}-{hi}")


async def acquire_free_port() -> int:
    """Thread-safe port allocation — holds the lock while picking the port."""
    async with _get_port_lock():
        return _free_port()


async def _launch_generated_app(run_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """Launch a generated app subprocess.

    Contains the full business logic (vite build, SQLite swap, uvicorn start).
    Inlined to avoid circular import: core must not depend on gateway.
    """
    from aether_os.core.run_app.process_manager import RunAppManager
    org_id = user.get("org_id")
    return await RunAppManager().start(run_id=run_id, org_id=org_id, user=user)
