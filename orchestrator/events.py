"""
AetherOS — Pipeline event bus for SSE streaming.

Kept in its own module so both the orchestrator and core LLM client
can import it without creating a circular dependency.

B3 fix: events are published to Redis pub/sub instead of a per-process
asyncio.Queue. All workers share the same event stream.
"""
from __future__ import annotations
import asyncio
import time
from contextvars import ContextVar
from typing import Optional

# Set by factory_pipeline before each phase so LLM calls can emit to the right queue.
ACTIVE_RUN_ID: ContextVar[Optional[str]] = ContextVar("active_run_id", default=None)
# Phase name currently executing (for tagging llm_chunk events)
ACTIVE_PHASE: ContextVar[Optional[str]] = ContextVar("active_phase", default=None)
# Org ID for the active run (for cost tracking)
ACTIVE_ORG_ID: ContextVar[Optional[str]] = ContextVar("active_org_id", default=None)


def emit_sync(event: dict, run_id: Optional[str] = None) -> None:
    """Non-async version — schedules Redis publish on the running event loop if available."""
    if run_id is None:
        run_id = ACTIVE_RUN_ID.get()
    if not run_id:
        return
    try:
        loop = asyncio.get_running_loop()
        from aether_os.core.pipeline_state import publish_event
        loop.create_task(publish_event(run_id, {**event, "ts": time.time()}))
    except RuntimeError:
        pass  # No running event loop — sync context, skip


async def emit(event: dict, run_id: Optional[str] = None) -> None:
    """Async version — publishes event to Redis for all workers to receive."""
    if run_id is None:
        run_id = ACTIVE_RUN_ID.get()
    if not run_id:
        return
    try:
        from aether_os.core.pipeline_state import publish_event
        await publish_event(run_id, {**event, "ts": time.time()})
    except Exception:
        pass
