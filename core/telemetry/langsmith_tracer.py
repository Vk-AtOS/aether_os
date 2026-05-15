"""
AetherOS — LangSmith observability tracer.

Gracefully disabled when LANGSMITH_API_KEY is not set or langsmith is not installed.
All public functions are safe to call unconditionally.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Module-level state ────────────────────────────────────────────────────────
_connected: bool = False
_ls_client = None          # langsmith.Client, or None
_last_trace_id: Optional[str] = None
_traces_today: int = 0
_traces_date: str = ""     # "YYYY-MM-DD" — used to reset _traces_today at midnight


# ── Initialisation ────────────────────────────────────────────────────────────

def init_langsmith() -> bool:
    """
    Initialise LangSmith from environment variables.

    Required env var: LANGSMITH_API_KEY
    Optional env vars: LANGCHAIN_TRACING_V2, LANGCHAIN_PROJECT

    Returns True if successfully connected, False if disabled or failed.
    Logs the outcome at INFO level — never raises.
    """
    global _connected, _ls_client

    api_key = os.environ.get("LANGSMITH_API_KEY", "").strip()
    if not api_key:
        logger.info("LangSmith: disabled — LANGSMITH_API_KEY not set")
        _connected = False
        return False

    try:
        import langsmith  # noqa: F401 — confirms package is installed
        # Only enable LangChain tracing if the operator has explicitly opted in.
        # Default is false — operators must set LANGCHAIN_TRACING_V2=true AND
        # LANGSMITH_API_KEY to enable tracing. Prevents data leakage for orgs
        # that set LANGSMITH_API_KEY without intending to enable call tracing.
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
        os.environ.setdefault("LANGCHAIN_PROJECT", "aetheros-factory")
        os.environ["LANGCHAIN_API_KEY"] = api_key

        _ls_client = langsmith.Client(api_key=api_key)
        # Light connectivity check — list at most 1 project
        list(_ls_client.list_projects(limit=1))
        _connected = True
        logger.info(
            "LangSmith: connected — project=%s",
            os.environ.get("LANGCHAIN_PROJECT", "aetheros-factory"),
        )
        return True
    except ImportError:
        logger.warning("LangSmith: 'langsmith' package not installed — tracing disabled")
    except Exception as exc:
        logger.warning("LangSmith: connection check failed (%s) — tracing disabled", exc)

    _connected = False
    return False


# ── Status helpers ────────────────────────────────────────────────────────────

def is_connected() -> bool:
    """Return True if LangSmith is initialised and reachable."""
    return _connected


def get_status() -> Dict[str, Any]:
    """Return the observability status dict for /health/observability."""
    return {
        "langsmith": "connected" if _connected else "disabled",
        "last_trace_id": _last_trace_id,
        "traces_today": _traces_today,
    }


# ── Trace context manager ─────────────────────────────────────────────────────

@asynccontextmanager
async def trace_call(name: str, inputs: Optional[Dict[str, Any]] = None):
    """
    Async context manager that wraps a block of code in a LangSmith run.

    Usage::

        async with trace_call("p02_architecture_<run_id>", inputs={"prompt": ...}):
            result = await do_llm_call(...)

    If LangSmith is disabled (no key or package missing), this is a **no-op**.
    The context yields the trace run-id string if connected, or None otherwise.
    Exceptions propagate unchanged — tracing never suppresses errors.
    """
    global _last_trace_id, _traces_today, _traces_date

    # Reset daily counter on calendar-day boundary
    today = time.strftime("%Y-%m-%d")
    if today != _traces_date:
        _traces_today = 0
        _traces_date = today

    if not _connected or _ls_client is None:
        yield None
        return

    import uuid
    from datetime import datetime, timezone

    run_id = str(uuid.uuid4())
    err: Optional[str] = None

    # Create the run record
    try:
        _ls_client.create_run(
            id=run_id,
            name=name,
            run_type="llm",
            inputs=inputs or {},
            start_time=datetime.now(timezone.utc),
        )
    except Exception as exc:
        logger.debug("LangSmith: create_run failed (%s) — skipping trace", exc)
        yield None
        return

    # Yield control to the wrapped code
    try:
        yield run_id
    except Exception as exc:
        err = str(exc)
        raise
    finally:
        # Always attempt to close the run, even on error
        try:
            from datetime import datetime, timezone
            _ls_client.update_run(
                run_id,
                end_time=datetime.now(timezone.utc),
                **({"error": err} if err else {"outputs": {"status": "ok"}}),
            )
            if not err:
                _last_trace_id = run_id
                _traces_today += 1
        except Exception as exc:
            logger.debug("LangSmith: update_run failed (%s)", exc)
