"""AetherOS — Message bus for inter-phase communication.

Primary backend: Redis RPUSH/BLPOP (cross-worker safe).
Fallback: asyncio.Queue (single-process mode when Redis is unavailable).
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Dict, Optional
from aether_os.orchestrator.messages import PhaseMessage, PhaseResult

logger = logging.getLogger(__name__)

_BUS_TTL = 3600          # Redis keys expire after 1 hour
_SUBSCRIBE_TIMEOUT = 120  # seconds to wait for a message before returning None


class MessageBus:
    """Per-run message bus. Uses Redis lists when available, asyncio.Queue otherwise."""

    def __init__(self, run_id: str) -> None:
        self._run_id = run_id
        self._prefix = f"aetheros:bus:{run_id}"
        # In-process fallback queues (used when Redis is unavailable)
        self._queue: asyncio.Queue[PhaseMessage] = asyncio.Queue()
        self._subscribers: Dict[str, asyncio.Queue[PhaseMessage]] = {}

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_redis(self):
        try:
            from aether_os.core.pipeline_state import get_redis
            return await get_redis()
        except Exception:
            return None

    def _serialize(self, message: PhaseMessage) -> str:
        return json.dumps({
            "from_phase": message.from_phase,
            "to_phase": message.to_phase,
            "run_id": message.result.run_id,
            "phase": message.result.phase,
            "status": message.result.status,
            "output_path": getattr(message.result, "output_path", ""),
            "artifacts": getattr(message.result, "artifacts", {}),
        })

    def _deserialize(self, raw: str) -> PhaseMessage:
        data = json.loads(raw)
        return PhaseMessage(
            from_phase=data.get("from_phase", ""),
            to_phase=data.get("to_phase"),
            result=PhaseResult(
                run_id=data.get("run_id", ""),
                phase=data.get("phase", ""),
                status=data.get("status", "unknown"),
                output_path=data.get("output_path", ""),
                artifacts=data.get("artifacts", {}),
            ),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def publish(self, message: PhaseMessage) -> None:
        target = message.to_phase
        redis = await self._get_redis()

        if redis is not None:
            try:
                raw = self._serialize(message)
                # Push to per-phase list so any worker can BLPOP it
                if target:
                    key = f"{self._prefix}:{target}"
                    await redis.rpush(key, raw)
                    await redis.expire(key, _BUS_TTL)
                # Also push to broadcast list for monitoring
                bkey = f"{self._prefix}:__broadcast__"
                await redis.rpush(bkey, raw)
                await redis.expire(bkey, _BUS_TTL)
            except Exception as exc:
                logger.debug("Bus publish Redis error: %s — falling back to in-process", exc)
                redis = None

        if redis is None:
            # Redis unavailable — in-process only delivery
            if target and target in self._subscribers:
                await self._subscribers[target].put(message)

        # Always push to in-process queue for drain() and local monitoring
        await self._queue.put(message)

        # Audit every message
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

    async def subscribe(self, phase_name: str) -> Optional[PhaseMessage]:
        """Wait for a message addressed to phase_name. Returns None on timeout."""
        redis = await self._get_redis()

        if redis is not None:
            try:
                key = f"{self._prefix}:{phase_name}"
                result = await redis.blpop(key, timeout=_SUBSCRIBE_TIMEOUT)
                if result:
                    _, raw = result
                    return self._deserialize(raw)
                return None
            except Exception as exc:
                logger.debug("Bus subscribe Redis error: %s — falling back to in-process", exc)

        # In-process fallback
        if phase_name not in self._subscribers:
            self._subscribers[phase_name] = asyncio.Queue()
        try:
            return await asyncio.wait_for(
                self._subscribers[phase_name].get(),
                timeout=_SUBSCRIBE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return None

    async def broadcast_status(self, run_id: str, phase: str, status: str) -> None:
        dummy = PhaseMessage(
            from_phase=phase,
            to_phase=None,
            result=PhaseResult(run_id=run_id, phase=phase, status=status),  # type: ignore[arg-type]
        )
        await self.publish(dummy)

    async def drain(self) -> list[PhaseMessage]:
        """Drain in-process queue. Always populated by publish() regardless of Redis."""
        msgs = []
        while not self._queue.empty():
            msgs.append(self._queue.get_nowait())
        return msgs


# ── Global registry ───────────────────────────────────────────────────────────

_buses: Dict[str, MessageBus] = {}


def get_bus(run_id: str) -> MessageBus:
    if run_id not in _buses:
        _buses[run_id] = MessageBus(run_id)
    return _buses[run_id]


def release_bus(run_id: str) -> None:
    _buses.pop(run_id, None)
