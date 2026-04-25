"""
AetherOS — Pipeline event bus for SSE streaming.

Kept in its own module so both the orchestrator and core LLM client
can import it without creating a circular dependency.
"""
from __future__ import annotations
import asyncio
import time
from contextvars import ContextVar
from typing import Dict, Optional

# One asyncio.Queue per run_id — created by factory_pipeline, drained by SSE endpoint.
PIPELINE_EVENTS: Dict[str, asyncio.Queue] = {}

# Set by factory_pipeline before each phase so LLM calls can emit to the right queue.
ACTIVE_RUN_ID: ContextVar[Optional[str]] = ContextVar("active_run_id", default=None)
# Phase name currently executing (for tagging llm_chunk events)
ACTIVE_PHASE: ContextVar[Optional[str]] = ContextVar("active_phase", default=None)


def emit_sync(event: dict, run_id: Optional[str] = None) -> None:
    """Non-async version — usable from sync code via put_nowait."""
    if run_id is None:
        run_id = ACTIVE_RUN_ID.get()
    if not run_id:
        return
    q = PIPELINE_EVENTS.get(run_id)
    if q:
        try:
            q.put_nowait({**event, "ts": time.time()})
        except asyncio.QueueFull:
            pass


async def emit(event: dict, run_id: Optional[str] = None) -> None:
    """
    Async version — puts event on the queue.
    Prefers explicit run_id; falls back to the ACTIVE_RUN_ID context var.
    """
    if run_id is None:
        run_id = ACTIVE_RUN_ID.get()
    if not run_id:
        return
    q = PIPELINE_EVENTS.get(run_id)
    if q:
        try:
            # Use put_nowait to avoid blocking the pipeline if no SSE client is reading
            q.put_nowait({**event, "ts": time.time()})
        except asyncio.QueueFull:
            pass  # Drop event if queue is full (no SSE client connected)
        except Exception:
            pass
