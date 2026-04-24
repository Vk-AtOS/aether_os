"""AetherOS — Async message bus for inter-phase communication."""
from __future__ import annotations
import asyncio
import logging
from typing import Dict, Optional
from aether_os.orchestrator.messages import PhaseMessage, PhaseResult

logger = logging.getLogger(__name__)


class MessageBus:
    """Single asyncio.Queue-based message bus. One instance per pipeline run."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[PhaseMessage] = asyncio.Queue()
        self._subscribers: Dict[str, asyncio.Queue[PhaseMessage]] = {}

    async def publish(self, message: PhaseMessage) -> None:
        await self._queue.put(message)
        # fan-out to per-phase subscribers
        target = message.to_phase
        if target and target in self._subscribers:
            await self._subscribers[target].put(message)
        # audit every message
        try:
            from aether_os.core.audit.logger import get_audit_logger
            get_audit_logger().log_sync(
                actor=message.from_phase,
                action="bus_publish",
                details={"to": target, "status": message.result.status,
                         "run_id": message.result.run_id},
                session_id=message.result.run_id,
            )
        except Exception:
            pass
        logger.info("Bus: %s → %s [%s]", message.from_phase, target or "broadcast",
                    message.result.status)

    async def subscribe(self, phase_name: str) -> PhaseMessage:
        if phase_name not in self._subscribers:
            self._subscribers[phase_name] = asyncio.Queue()
        return await self._subscribers[phase_name].get()

    async def broadcast_status(self, run_id: str, phase: str, status: str) -> None:
        dummy = PhaseMessage(
            from_phase=phase,
            to_phase=None,
            result=PhaseResult(run_id=run_id, phase=phase, status=status),  # type: ignore[arg-type]
        )
        await self._queue.put(dummy)

    async def drain(self) -> list[PhaseMessage]:
        """Drain all pending messages (for testing)."""
        msgs = []
        while not self._queue.empty():
            msgs.append(self._queue.get_nowait())
        return msgs


# Global bus registry keyed by run_id
_buses: Dict[str, MessageBus] = {}


def get_bus(run_id: str) -> MessageBus:
    if run_id not in _buses:
        _buses[run_id] = MessageBus()
    return _buses[run_id]


def release_bus(run_id: str) -> None:
    _buses.pop(run_id, None)
