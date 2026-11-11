"""
AetherOS — Decision Ledger (Run/Event Log) — ORM edition (C1)

Migrated from raw sqlite3 to SQLAlchemy async ORM.
External API is unchanged so no callers need updating.

Audit events are also appended to the tamper-evident hash chain in
core/audit/chain.py (append / verify). Nothing here updates or deletes them.

Async methods use the ORM session factory directly.
Sync methods (used by sync pipeline code) delegate to the async API
via a fresh event loop, avoiding event-loop-not-running errors.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
import weakref
from typing import Any, Dict, List, Optional, Union

from aether_os.core.audit import chain as audit_chain
from aether_os.core import db as core_db  # module ref: tests patch core.db.get_session_factory
from aether_os.core.models import AuditLog
from aether_os.core.security.redact import redact_secrets

logger = logging.getLogger(__name__)

# M5: track all fire-and-forget audit futures in a WeakSet so callers can
# drain them during graceful shutdown instead of silently losing events.
_active_audit_futures: weakref.WeakSet = weakref.WeakSet()

# Audit events whose audit_chain append failed since process start. Each such
# audit_log row is also stored with metadata["chain_linked"] = False.
_unlinked_audit_events = 0


def unlinked_audit_event_count() -> int:
    """How many audit events this process wrote without a chain link (should be 0)."""
    return _unlinked_audit_events


class DecisionLedger:
    _instance: Optional["DecisionLedger"] = None

    def __init__(self) -> None:
        pass  # No file path needed — uses the shared ORM session factory

    # ── Sync API (legacy — delegates to async methods) ────────────────────────

    def save_run(self, run_id: str, command: str, org_id: Optional[str] = None,
                 status: str = "running") -> None:
        _run_async(self.async_save_run(run_id, command, org_id, status))

    def update_run_status(self, run_id: str, status: str) -> None:
        _run_async(self.async_update_run_status(run_id, status))

    def log_event(self, run_id: str, agent: str, action: str,
                  detail: Union[str, Dict[str, Any]]) -> None:
        _run_async(self.async_log_event(run_id, agent, action, detail))

    def log_audit_event(self, org_id: str, user_id: str, action: str,
                        resource_type: str, resource_id: str,
                        metadata: Dict[str, Any], ip_address: str) -> None:
        _run_async(self.async_log_audit_event(
            org_id, user_id, action, resource_type, resource_id, metadata, ip_address
        ))

    def get_audit_logs(self, org_id: str, page: int = 1, limit: int = 50,
                       action: Optional[str] = None,
                       from_ts: Optional[float] = None) -> Dict[str, Any]:
        return _run_async(self.async_get_audit_logs(org_id, page, limit, action, from_ts))

    def get_run_history(self, org_id: Optional[str] = None,
                        limit: int = 20) -> List[Dict[str, Any]]:
        return _run_async(self.async_get_run_history(org_id, limit))

    def get_run_detail(self, run_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
        return _run_async(self.async_get_run_detail(run_id, org_id))

    # ── Async API ─────────────────────────────────────────────────────────────

    async def async_save_run(self, run_id: str, command: str,
                              org_id: Optional[str] = None,
                              status: str = "running") -> None:
        try:
            from aether_os.core.models import Run
            sf = core_db.get_session_factory()
            async with sf() as session:
                existing = await session.get(Run, run_id)
                if existing:
                    existing.status = status
                    existing.command = command
                else:
                    session.add(Run(
                        id=run_id, command=command, org_id=org_id,
                        status=status, started_at=time.time(),
                    ))
                await session.commit()
        except Exception as exc:
            logger.debug("async_save_run failed: %s", exc)

    async def async_update_run_status(self, run_id: str, status: str,
                                      message: Optional[str] = None) -> None:
        """`message` is the human-readable reason shown on the run's page (used on failure).

        Callers build it from exception text, so it is redacted and length-capped here,
        the one place every Run.message passes through, before it is stored.
        """
        try:
            from aether_os.core.db_utils import update_run_status
            await update_run_status(
                run_id, status,
                message=redact_secrets(message) if message is not None else None)
        except Exception as exc:
            logger.debug("async_update_run_status failed: %s", exc)

    async def async_log_event(self, run_id: str, agent: str, action: str,
                               detail: Union[str, Dict[str, Any]]) -> None:
        try:
            from aether_os.core.models import Event
            detail_str = json.dumps(detail) if isinstance(detail, dict) else str(detail)
            sf = core_db.get_session_factory()
            async with sf() as session:
                session.add(Event(
                    id=str(uuid.uuid4()), run_id=run_id,
                    agent=agent, action=action,
                    detail=detail_str, timestamp=time.time(),
                ))
                await session.commit()
        except Exception as exc:
            logger.debug("async_log_event failed: %s", exc)

    async def async_log_audit_event(self, org_id: str, user_id: str, action: str,
                                    resource_type: str = "", resource_id: str = "",
                                    metadata: Optional[Dict[str, Any]] = None,
                                    ip_address: str = "", user_agent: str = "-") -> None:
        """Record an audit event: one hash-chained entry (audit_chain) plus the
        queryable audit_log row the compliance/admin endpoints read.

        Never raises — callers fire this with asyncio.create_task. Failures are logged.
        """
        global _unlinked_audit_events
        ts = time.time()
        entry_hash: Optional[str] = None
        row_metadata = metadata or {}
        try:
            entry = await audit_chain.append(
                actor=user_id, action=action, timestamp=ts,
                payload={"org_id": org_id, "resource_type": resource_type,
                         "resource_id": resource_id, "metadata": metadata or {},
                         "ip_address": ip_address},
            )
            entry_hash = entry.entry_hash
        except Exception as exc:
            # Never silent: counted, logged at error level, and the row itself is
            # flagged so unlinked events can be found with a query afterwards.
            _unlinked_audit_events += 1
            row_metadata = {**row_metadata, "chain_linked": False}
            logger.error(
                "AUDIT CHAIN LINK FAILED action=%s org=%s (unlinked since start: %d): %s",
                action, org_id, _unlinked_audit_events, exc)
        try:
            sf = core_db.get_session_factory()
            async with sf() as session:
                session.add(AuditLog(
                    id=str(uuid.uuid4()), org_id=org_id, user_id=user_id,
                    action=action, resource_type=resource_type,
                    resource_id=resource_id,
                    log_metadata=json.dumps(row_metadata),
                    ip_address=ip_address, created_at=ts,
                    # Legacy column name: it now holds the entry_hash of this
                    # event's audit_chain entry, linking the row to the chain.
                    prev_hash=entry_hash,
                ))
                await session.commit()
        except Exception as exc:
            # ARCH-H2: WARNING so failures appear in production logs (DEBUG is off by default).
            # Audit write failures are a SOC-2/GDPR liability.
            logger.warning("async_log_audit_event failed: %s", exc)

    async def async_get_audit_logs(self, org_id: str, page: int = 1,
                                   limit: int = 50, action: Optional[str] = None,
                                   from_ts: Optional[float] = None) -> Dict[str, Any]:
        try:
            from sqlalchemy import select, func

            sf = core_db.get_session_factory()
            async with sf() as session:
                q = select(AuditLog).where(AuditLog.org_id == org_id)
                if action:
                    q = q.where(AuditLog.action == action)
                if from_ts:
                    q = q.where(AuditLog.created_at >= from_ts)

                total = (await session.execute(
                    select(func.count()).select_from(q.subquery())
                )).scalar_one()

                rows = (await session.execute(
                    q.order_by(AuditLog.created_at.desc())
                    .limit(limit).offset((page - 1) * limit)
                )).scalars().all()

            return {
                "logs": [
                    {
                        "id": r.id, "org_id": r.org_id, "user_id": r.user_id,
                        "action": r.action, "resource_type": r.resource_type,
                        "resource_id": r.resource_id,
                        "metadata": _safe_json(r.log_metadata),
                        "ip_address": r.ip_address, "created_at": r.created_at,
                    }
                    for r in rows
                ],
                "total": total,
                "page": page,
                "pages": max(1, (total + limit - 1) // limit),
            }
        except Exception as exc:
            logger.debug("async_get_audit_logs failed: %s", exc)
            return {"logs": [], "total": 0, "page": page, "pages": 1}

    async def async_get_run_history(
        self,
        org_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        cursor: Optional[float] = None,
    ) -> Dict[str, Any]:
        try:
            from aether_os.core.db_utils import get_run_list
            if org_id:
                return await get_run_list(org_id=org_id, limit=limit, offset=offset, cursor=cursor)
            return {"items": [], "total": 0, "next_cursor": None}
        except Exception as exc:
            logger.debug("async_get_run_history failed: %s", exc)
            return {"items": [], "total": 0, "next_cursor": None}

    async def async_get_run_detail(self, run_id: str,
                                   org_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            from aether_os.core.db_utils import get_run_detail
            return await get_run_detail(run_id=run_id, org_id=org_id)
        except Exception as exc:
            logger.warning("async_get_run_detail failed for run_id=%s: %s", run_id, exc)
            return {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_json(value: Optional[str]) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception as e:
        logger.warning("_safe_json could not decode value: %s", e)
        return value


def _run_async(coro) -> Any:
    """Run a coroutine from sync code. Creates a new event loop if needed.

    When called from a running event loop, the coroutine is scheduled as a
    fire-and-forget asyncio Task tracked in _active_audit_futures so
    drain_audit_futures() can await completion during graceful shutdown —
    preventing silent audit event loss on teardown.
    """
    try:
        loop = asyncio.get_running_loop()
        # Inside a running loop — cannot block. Schedule fire-and-forget Task
        # and track it so drain_audit_futures() can await it on shutdown.
        task = asyncio.ensure_future(coro, loop=loop)
        _active_audit_futures.add(task)

        def _cleanup(f, _ws=_active_audit_futures):
            _ws.discard(f)

        task.add_done_callback(_cleanup)
        return None
    except RuntimeError:
        # No running loop (pure sync context) — use asyncio.run()
        return asyncio.run(coro)
    except Exception as exc:
        logger.debug("_run_async failed: %s", exc)
        return None


async def drain_audit_futures(timeout: float = 5.0) -> None:
    """Await all pending fire-and-forget audit futures. Call during graceful shutdown.

    Prevents audit events from being silently lost when the event loop is torn
    down before the asyncio Tasks scheduled by _run_async have completed.
    """
    futs = list(_active_audit_futures)
    if futs:
        await asyncio.wait(futs, timeout=timeout)


# ── Singleton ─────────────────────────────────────────────────────────────────

def get_ledger() -> DecisionLedger:
    if DecisionLedger._instance is None:
        DecisionLedger._instance = DecisionLedger()
    return DecisionLedger._instance
