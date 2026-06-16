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
import os
from typing import Any, Dict, Optional

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
    """Return an unused TCP port on localhost."""
    import socket as _sock
    with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def acquire_free_port() -> int:
    """Thread-safe port allocation — holds the lock while picking the port."""
    async with _get_port_lock():
        return _free_port()


async def _launch_generated_app(run_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """Launch a generated app subprocess.

    Delegates to the router's start_run_app function which contains the full
    business logic (vite build, SQLite swap, uvicorn start).  This indirection
    keeps the orchestrator layer from importing the HTTP router layer directly.
    """
    from aether_os.gateway.routers.run_app_router import start_run_app
    return await start_run_app(run_id=run_id, user=user)
