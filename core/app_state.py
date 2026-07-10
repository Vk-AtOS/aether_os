"""
AetherOS — Shared App-Process State

Stores ephemeral run-app metadata (port, pid, mode, app_dir) in Redis with a
2-hour TTL so it survives across uvicorn worker processes and gateway restarts.
Falls back to an in-memory dict when Redis is unavailable (single-worker dev mode).

subprocess.Popen objects cannot be serialised to Redis; they are kept in the
module-level _PROCS dict and accessed via get_proc / set_proc / del_proc.

Redis keys
----------
app:state:{run_id}   → JSON  {port, pid, mode, app_dir, run_id, started_at}
app:current_run      → plain string run_id

TTL for both keys: _APP_STATE_TTL seconds (7 200 = 2 hours).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_APP_STATE_TTL = 7_200  # 2 hours

_KEY_PREFIX = "app:state:"
_KEY_CURRENT = "app:current_run"

# ── In-memory fallbacks ───────────────────────────────────────────────────────

# Keyed by run_id; holds {port, pid, mode, app_dir, run_id, started_at}
_STATE_MEMORY: dict[str, dict] = {}

# Single-element list: [run_id] of the most-recently started run-app.
# A list (rather than a bare str) is intentional — the original api.py used the
# same pattern so identity-mutation propagates to any code that holds a reference.
_CURRENT_RUN_MEMORY: list[str] = []

# ── Popen registry (cannot go to Redis) ──────────────────────────────────────

_PROCS: dict[str, Any] = {}
_APP_PORTS: dict[str, int] = {}  # in-process port cache (populated by set_app_state)


def get_proc(run_id: str) -> Any | None:
    """Return the subprocess.Popen object for *run_id*, or None."""
    return _PROCS.get(run_id)


def set_proc(run_id: str, proc: Any) -> None:
    """Register *proc* (a Popen-like object) for *run_id*."""
    _PROCS[run_id] = proc


def del_proc(run_id: str) -> None:
    """Remove the Popen entry for *run_id* (no-op if absent)."""
    _PROCS.pop(run_id, None)


def get_all_procs() -> dict:
    """Return the live _PROCS dict (caller must not mutate keys externally)."""
    return _PROCS


def get_all_ports() -> dict[str, int]:
    """Return the in-process port cache dict."""
    return _APP_PORTS


def get_port(run_id: str) -> int | None:
    return _APP_PORTS.get(run_id)


def set_port(run_id: str, port: int) -> None:
    _APP_PORTS[run_id] = port


def del_port(run_id: str) -> None:
    _APP_PORTS.pop(run_id, None)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state_key(run_id: str) -> str:
    return f"{_KEY_PREFIX}{run_id}"


# ── Async public API ──────────────────────────────────────────────────────────

async def set_app_state(
    run_id: str,
    port: int,
    pid: int,
    mode: str,
    app_dir: str,
) -> None:
    """Persist app-process metadata to Redis (with in-memory fallback)."""
    from aether_os.core.rate_limiter import _get_async_redis  # local import — avoids circular

    payload = {
        "run_id": run_id,
        "port": port,
        "pid": pid,
        "mode": mode,
        "app_dir": app_dir,
        "started_at": time.time(),
    }
    serialised = json.dumps(payload)
    _APP_PORTS[run_id] = port  # always update in-process cache

    r = await _get_async_redis()
    if r is not None:
        try:
            await r.set(_state_key(run_id), serialised, ex=_APP_STATE_TTL)
            await r.set(_KEY_CURRENT, run_id, ex=_APP_STATE_TTL)
            # Mirror into memory so same-process reads are always fast
            _STATE_MEMORY[run_id] = payload
            if _CURRENT_RUN_MEMORY:
                _CURRENT_RUN_MEMORY[0] = run_id
            else:
                _CURRENT_RUN_MEMORY.append(run_id)
            return
        except Exception as exc:
            logger.warning("app_state: Redis write failed for run %s: %s", run_id, exc)

    # Fallback: in-memory only
    _STATE_MEMORY[run_id] = payload
    if _CURRENT_RUN_MEMORY:
        _CURRENT_RUN_MEMORY[0] = run_id
    else:
        _CURRENT_RUN_MEMORY.append(run_id)


async def get_app_state(run_id: str) -> dict | None:
    """
    Return {port, pid, mode, app_dir, run_id} for *run_id*, or None if unknown.

    Resolution order:
      1. In-memory _STATE_MEMORY (same-process cache)
      2. Redis (cross-worker)
    """
    from aether_os.core.rate_limiter import _get_async_redis

    # 1. Same-process memory hit
    cached = _STATE_MEMORY.get(run_id)
    if cached:
        return {k: cached[k] for k in ("port", "pid", "mode", "app_dir", "run_id")}

    # 2. Redis
    r = await _get_async_redis()
    if r is not None:
        try:
            raw = await r.get(_state_key(run_id))
            if raw:
                payload = json.loads(raw)
                # Warm the local cache
                _STATE_MEMORY[run_id] = payload
                return {k: payload[k] for k in ("port", "pid", "mode", "app_dir", "run_id")}
        except Exception as exc:
            logger.warning("app_state: Redis read failed for run %s: %s", run_id, exc)

    return None


async def get_current_run_id() -> str | None:
    """Return the run_id of the most-recently started app, or None."""
    from aether_os.core.rate_limiter import _get_async_redis

    # 1. Same-process memory
    if _CURRENT_RUN_MEMORY:
        return _CURRENT_RUN_MEMORY[0]

    # 2. Redis
    r = await _get_async_redis()
    if r is not None:
        try:
            val = await r.get(_KEY_CURRENT)
            if val:
                # Warm in-memory list so subsequent same-process calls are free
                if _CURRENT_RUN_MEMORY:
                    _CURRENT_RUN_MEMORY[0] = val
                else:
                    _CURRENT_RUN_MEMORY.append(val)
                return val
        except Exception as exc:
            logger.warning("app_state: Redis read for current_run failed: %s", exc)

    return None


async def set_current_run_id(run_id: str) -> None:
    """Mark *run_id* as the most-recently started app in both Redis and memory."""
    from aether_os.core.rate_limiter import _get_async_redis

    r = await _get_async_redis()
    if r is not None:
        try:
            await r.set(_KEY_CURRENT, run_id, ex=_APP_STATE_TTL)
        except Exception as exc:
            logger.warning("app_state: Redis write for current_run failed: %s", exc)

    if _CURRENT_RUN_MEMORY:
        _CURRENT_RUN_MEMORY[0] = run_id
    else:
        _CURRENT_RUN_MEMORY.append(run_id)


async def clear_app_state(run_id: str) -> None:
    """Remove all stored state for *run_id*; clears current_run if it matches."""
    from aether_os.core.rate_limiter import _get_async_redis

    r = await _get_async_redis()
    if r is not None:
        try:
            await r.delete(_state_key(run_id))
            # Only clear current_run if it points at this run
            current = await r.get(_KEY_CURRENT)
            if current == run_id:
                await r.delete(_KEY_CURRENT)
        except Exception as exc:
            logger.warning("app_state: Redis delete failed for run %s: %s", run_id, exc)

    _STATE_MEMORY.pop(run_id, None)
    _APP_PORTS.pop(run_id, None)
    if _CURRENT_RUN_MEMORY and _CURRENT_RUN_MEMORY[0] == run_id:
        _CURRENT_RUN_MEMORY.clear()
