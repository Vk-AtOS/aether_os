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
from contextvars import ContextVar
from typing import Any, Optional

from aether_os.core import pipeline_state
from aether_os.core.security.redact import redact_secrets

logger = logging.getLogger(__name__)

# Set by factory_pipeline before each phase so LLM calls can emit to the right queue.
ACTIVE_RUN_ID: ContextVar[Optional[str]] = ContextVar("active_run_id", default=None)
# Phase name currently executing (for tagging llm_chunk events)
ACTIVE_PHASE: ContextVar[Optional[str]] = ContextVar("active_phase", default=None)
# Org ID for the active run (for cost tracking)
ACTIVE_ORG_ID: ContextVar[Optional[str]] = ContextVar("active_org_id", default=None)


# Event fields that carry free text built from exceptions or gate issues.
_TEXT_KEYS = frozenset({"error", "message", "reason", "detail", "warning", "issues"})


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    return value


def redact_event(event: dict) -> dict:
    """Copy of `event` with credentials masked in its free-text fields.

    Exception text routinely carries connection URLs and keys, and the event
    stream is shown live in the browser and stored in pipeline_events.
    """
    return {k: _redact(v) if k in _TEXT_KEYS else v for k, v in event.items()}


async def publish_event(run_id: str, event: dict) -> None:
    """The one path from the orchestrator to the live event stream: redact, then publish."""
    await pipeline_state.publish_event(run_id, redact_event(event))


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
