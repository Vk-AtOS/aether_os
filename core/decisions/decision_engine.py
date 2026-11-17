"""
AetherOS — Decision Engine

Tracks human-approval-required decisions during pipeline runs.
Each Decision is stored in the ORM Decision table and the waiter
block is implemented via Redis pub/sub — so it works correctly
across multiple uvicorn workers.

Used by pipeline phases that need human sign-off before proceeding
(e.g. architecture choices, payment-logic changes, deploy gates).
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

_REDIS_CHANNEL_PREFIX = "aether:decisions:"
_DEFAULT_TIMEOUT = 300  # seconds


@dataclass
class Decision:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    org_id: str = ""
    decision_type: str = ""
    title: str = ""
    what: str = ""
    why: str = ""
    alternatives: List[str] = field(default_factory=list)
    impact: str = ""
    phase: str = ""
    status: str = "pending"        # pending | approved | denied | timeout
    human_choice: Optional[str] = None
    timeout_seconds: int = _DEFAULT_TIMEOUT
    created_at: float = field(default_factory=time.time)
    decided_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Decision":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class AlreadyDecided(Exception):
    """The decision is no longer pending."""


class DecisionEngine:
    """
    Redis-backed decision store — works across multiple uvicorn workers.

    Pipeline phases call request_approval() + await_decision() to block
    until an operator resolves the decision via /decisions/{id}/resolve.
    """

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get(self, decision_id: str) -> Optional[Decision]:
        row = await self._db_get(decision_id)
        return row

    async def list_for_run(self, run_id: str, status: Optional[str] = None) -> List[Decision]:
        return await self._db_list(run_id=run_id, status=status)

    async def list_for_org(self, org_id: str, status: Optional[str] = None,
                           limit: int = 50, offset: int = 0) -> List[Decision]:
        """Decisions of one organisation, newest first. A DB failure raises: an approver must not see an
        empty inbox when the query actually failed (unlike the per-run list, which logs and returns [])."""
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Decision as DecisionModel
        from sqlalchemy import select

        q = select(DecisionModel).where(DecisionModel.org_id == org_id)
        if status:
            q = q.where(DecisionModel.status == status)
        q = q.order_by(DecisionModel.created_at.desc()).limit(limit).offset(offset)
        async with get_session_factory()() as session:
            rows = (await session.execute(q)).scalars().all()
        return [Decision(
            id=r.id, run_id=r.run_id, org_id=r.org_id, decision_type=r.decision_type, title=r.title,
            what=r.what, why=r.why, alternatives=r.alternatives or [], impact=r.impact or "",
            phase=r.phase or "", status=r.status, human_choice=r.human_choice,
            timeout_seconds=r.timeout_seconds,
            created_at=r.created_at.timestamp() if r.created_at else time.time(),
            decided_at=r.decided_at.timestamp() if r.decided_at else None) for r in rows]

    # ── Write ─────────────────────────────────────────────────────────────────

    async def request_approval(self, decision: Decision) -> Decision:
        """Register a new pending decision in the DB and return it."""
        await self._db_save(decision)
        logger.info(
            "[decisions] Approval requested: %s '%s' (run=%s phase=%s)",
            decision.decision_type, decision.title, decision.run_id, decision.phase,
        )
        return decision

    async def await_decision(self, decision_id: str, timeout: Optional[float] = None) -> Decision:
        """
        Block until the decision is resolved or times out.
        Uses Redis pub/sub so it works across workers.
        Falls back to polling if Redis is unavailable.
        """
        decision = await self._db_get(decision_id)
        if not decision:
            raise LookupError(f"Decision {decision_id} not found")
        if decision.status != "pending":
            return decision

        effective_timeout = timeout or float(decision.timeout_seconds)
        channel = f"{_REDIS_CHANNEL_PREFIX}{decision_id}"

        try:
            from aether_os.core.pipeline_state import get_redis
            r = await get_redis()
            if r is not None:
                return await self._wait_redis(decision, channel, effective_timeout, r)
        except Exception as exc:
            logger.debug("[decisions] Redis wait failed, falling back to polling: %s", exc)

        return await self._wait_poll(decision_id, effective_timeout)

    async def resolve(
        self,
        decision_id: str,
        org_id: str,
        approved: bool,
        choice: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Decision:
        """Approve or deny a pending decision and publish to Redis.

        Raises LookupError (unknown, or not a decision of `run_id`), PermissionError (other org) and
        AlreadyDecided: a second approver or a late click must not flip an outcome the pipeline already acted on.
        """
        decision = await self._db_get(decision_id)
        if not decision or (run_id is not None and decision.run_id != run_id):
            raise LookupError(f"Decision {decision_id} not found")
        if decision.org_id and decision.org_id != org_id:
            raise PermissionError("Decision belongs to a different org")
        if decision.status != "pending":
            raise AlreadyDecided(f"Decision {decision_id} is already {decision.status}")

        new_status = "approved" if approved else "denied"
        decided_at = time.time()
        # The check above is only a fast path. THIS statement decides: UPDATE .. WHERE status='pending' changes a row
        # for exactly one of two simultaneous clicks (or a click racing the timeout), the other changes none.
        if not await self._db_claim(decision_id, new_status, choice, decided_at):
            current = await self._db_get(decision_id)
            raise AlreadyDecided(f"Decision {decision_id} is already {current.status if current else 'decided'}")
        decision.status, decision.human_choice, decision.decided_at = new_status, choice, decided_at

        # Notify waiting workers via Redis pub/sub
        try:
            from aether_os.core.pipeline_state import get_redis
            r = await get_redis()
            if r:
                channel = f"{_REDIS_CHANNEL_PREFIX}{decision_id}"
                await r.publish(channel, json.dumps(decision.to_dict()))
        except Exception as exc:
            logger.debug("[decisions] Redis publish failed: %s", exc)

        logger.info("[decisions] Decision %s resolved: %s", decision_id, decision.status)
        return decision

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _wait_redis(self, decision: Decision, channel: str, timeout: float, r) -> Decision:
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)
        try:
            # Decided between the caller's read and our subscribe: nothing will be published.
            current = await self._db_get(decision.id)
            if current is not None and current.status != "pending":
                return current
            deadline = time.monotonic() + timeout
            while (remaining := deadline - time.monotonic()) > 0:
                # listen() blocks forever on a quiet channel, so the deadline was never
                # checked; get_message() returns after at most `timeout` seconds.
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=min(remaining, 5.0))
                if not message or message.get("type") != "message":
                    continue
                try:
                    return Decision.from_dict(json.loads(message["data"]))
                except Exception as exc:
                    logger.debug("[decisions] could not parse Redis message: %s", exc)
            logger.warning("[decisions] Redis pub/sub wait timed out after %ss for decision %s", timeout, decision.id)
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception as exc:
                logger.debug("[decisions] error closing Redis pubsub: %s", exc)

        decision.status = "timeout"
        decision.decided_at = time.time()
        await self._db_save(decision)
        return decision

    async def _wait_poll(self, decision_id: str, timeout: float) -> Decision:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            decision = await self._db_get(decision_id)
            if decision and decision.status != "pending":
                return decision

        decision = await self._db_get(decision_id)
        if decision:
            decision.status = "timeout"
            decision.decided_at = time.time()
            await self._db_save(decision)
            return decision
        raise LookupError(f"Decision {decision_id} not found")

    # ── DB persistence ────────────────────────────────────────────────────────

    async def _db_claim(self, decision_id: str, status: str, choice: Optional[str], decided_at: float) -> bool:
        """Atomically move a decision from pending to `status`. True for the one caller that did it."""
        from datetime import datetime
        from sqlalchemy import update
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Decision as DecisionModel

        async with get_session_factory()() as session:
            res = await session.execute(
                update(DecisionModel)
                .where(DecisionModel.id == decision_id, DecisionModel.status == "pending")
                .values(status=status, human_choice=choice, decided_at=datetime.fromtimestamp(decided_at)))
            await session.commit()
        return res.rowcount == 1

    async def _db_save(self, decision: Decision) -> None:
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Decision as DecisionModel
            from sqlalchemy import select
            from datetime import datetime

            sf = get_session_factory()
            async with sf() as session:
                row = (await session.execute(
                    select(DecisionModel).where(DecisionModel.id == decision.id)
                )).scalar_one_or_none()

                decided_at = datetime.fromtimestamp(decision.decided_at) if decision.decided_at else None
                if row:
                    row.status = decision.status
                    row.human_choice = decision.human_choice
                    row.decided_at = decided_at
                else:
                    row = DecisionModel(
                        id=decision.id,
                        run_id=decision.run_id,
                        org_id=decision.org_id,
                        decision_type=decision.decision_type,
                        title=decision.title,
                        what=decision.what,
                        why=decision.why,
                        alternatives=decision.alternatives,
                        impact=decision.impact,
                        phase=decision.phase,
                        status=decision.status,
                        human_choice=decision.human_choice,
                        timeout_seconds=decision.timeout_seconds,
                        decided_at=decided_at,
                    )
                    session.add(row)
                await session.commit()
        except Exception as exc:
            logger.debug("[decisions] DB save failed: %s", exc)

    async def _db_get(self, decision_id: str) -> Optional[Decision]:
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Decision as DecisionModel
            from sqlalchemy import select

            sf = get_session_factory()
            async with sf() as session:
                row = (await session.execute(
                    select(DecisionModel).where(DecisionModel.id == decision_id)
                )).scalar_one_or_none()
                if not row:
                    return None
                return Decision(
                    id=row.id, run_id=row.run_id, org_id=row.org_id,
                    decision_type=row.decision_type, title=row.title,
                    what=row.what, why=row.why,
                    alternatives=row.alternatives or [],
                    impact=row.impact or "", phase=row.phase or "",
                    status=row.status, human_choice=row.human_choice,
                    timeout_seconds=row.timeout_seconds,
                    created_at=row.created_at.timestamp() if row.created_at else time.time(),
                    decided_at=row.decided_at.timestamp() if row.decided_at else None,
                )
        except Exception as exc:
            logger.debug("[decisions] DB get failed: %s", exc)
            return None

    async def _db_list(self, run_id: str, status: Optional[str] = None) -> List[Decision]:
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Decision as DecisionModel
            from sqlalchemy import select

            sf = get_session_factory()
            async with sf() as session:
                q = select(DecisionModel).where(DecisionModel.run_id == run_id)
                if status:
                    q = q.where(DecisionModel.status == status)
                rows = (await session.execute(q)).scalars().all()
                return [
                    Decision(
                        id=r.id, run_id=r.run_id, org_id=r.org_id,
                        decision_type=r.decision_type, title=r.title,
                        what=r.what, why=r.why,
                        alternatives=r.alternatives or [],
                        impact=r.impact or "", phase=r.phase or "",
                        status=r.status, human_choice=r.human_choice,
                        timeout_seconds=r.timeout_seconds,
                        created_at=r.created_at.timestamp() if r.created_at else time.time(),
                        decided_at=r.decided_at.timestamp() if r.decided_at else None,
                    )
                    for r in rows
                ]
        except Exception as exc:
            logger.debug("[decisions] DB list failed: %s", exc)
            return []


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: Optional[DecisionEngine] = None


def get_decision_engine() -> DecisionEngine:
    global _engine
    if _engine is None:
        _engine = DecisionEngine()
    return _engine
