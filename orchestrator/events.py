"""
AetherOS — Pipeline event bus for SSE streaming.

Kept in its own module so both the orchestrator and core LLM client
can import it without creating a circular dependency.

B3 fix: events are published to Redis pub/sub instead of a per-process
asyncio.Queue. All workers share the same event stream.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Optional

from aether_os.core import pipeline_state

logger = logging.getLogger(__name__)

# The context vars live in core.run_context (KAN-183); re-exported for existing callers.
from aether_os.core.run_context import ACTIVE_RUN_ID, ACTIVE_PHASE, ACTIVE_ORG_ID  # noqa: E402,F401


# Redaction happens inside core.pipeline_state.publish_event, so every publisher —
# not only the orchestrator — goes through it. Re-exported here for existing callers.
redact_event = pipeline_state.redact_event


async def publish_event(run_id: str, event: dict) -> None:
    """Publish through core.pipeline_state (looked up per call so it can be replaced in tests)."""
    await pipeline_state.publish_event(run_id, event)


def emit_sync(event: dict, run_id: Optional[str] = None) -> None:
    """Non-async version — schedules Redis publish on the running event loop if available."""
    if run_id is None:
        run_id = ACTIVE_RUN_ID.get()
    if not run_id:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(publish_event(run_id, {**event, "ts": time.time()}))
    except RuntimeError as e:
        logger.warning("orchestrator/events: no running event loop in emit_sync for run_id=%s: %s", run_id, e)


async def emit(event: dict, run_id: Optional[str] = None) -> None:
    """Async version — publishes event to Redis for all workers to receive."""
    if run_id is None:
        run_id = ACTIVE_RUN_ID.get()
    if not run_id:
        return
    try:
        await publish_event(run_id, {**event, "ts": time.time()})
    except Exception as exc:
        logger.debug("emit failed for run_id=%s (non-fatal): %s", run_id, exc)
