"""
AetherOS SQS pipeline consumer.

Polls the SQS queue for pending pipeline jobs and executes them using the same
factory.run() path as the direct-execution path. Activated at startup when
SQS_QUEUE_URL is set. Runs as a background asyncio task — one consumer per
server process. Pair with PIPELINE_MAX_CONCURRENT=2 to cap load per node.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CONSUMER_TASK: Optional[asyncio.Task] = None
_RUNNING = False

HEARTBEAT_S = 300            # re-extend visibility well inside the 3600 s it is extended to
MAX_RECEIVES = int(os.environ.get("SQS_MAX_RECEIVES", "3"))   # then: poison message -> DLQ
_slots: Optional[asyncio.Semaphore] = None   # bounded in-flight jobs per process (backpressure)
_inflight: set = set()
# Per-job-class pools (KAN-49): a flood of one class cannot occupy every slot. Order matters only for the docs.
CLASSES = ("interactive", "standard", "bulk")
_pools: Dict[str, asyncio.Semaphore] = {}
_waiting = 0                  # received jobs parked until their class pool has room (they hold no run slot)
WAIT_LIMIT_S = 1800           # inside the 3600 s visibility the receive set; past it the message goes back


def _max_inflight() -> int:
    return max(1, int(os.environ.get("SQS_MAX_INFLIGHT", os.environ.get("PIPELINE_MAX_CONCURRENT", "2"))))


def job_class(params: Dict[str, Any]) -> str:
    """interactive: a high-priority run; bulk: low priority or a whole-codebase import (long, heavy); else standard."""
    if params.get("codebase_mode") or params.get("priority") == "low":
        return "bulk"
    return "interactive" if params.get("priority") == "high" else "standard"


def class_limits() -> Dict[str, int]:
    """Concurrent jobs per class on this process. Defaults: bulk may use half the slots (at least 1) so it can never
    take them all; override with SQS_POOL_INTERACTIVE / SQS_POOL_STANDARD / SQS_POOL_BULK."""
    total = _max_inflight()
    default = {"interactive": total, "standard": total, "bulk": max(1, total // 2)}
    return {c: max(1, int(os.environ.get(f"SQS_POOL_{c.upper()}", default[c]))) for c in CLASSES}


def _max_waiting() -> int:
    return max(1, int(os.environ.get("SQS_MAX_WAITING", "4")))


async def _park_poison(job: Dict[str, Any]) -> None:
    """A job received MAX_RECEIVES times keeps failing: mark the run failed, park the body, delete it."""
    from aether_os.core.queue.sqs_client import delete_job, send_to_dlq
    run_id = job["run_id"]
    reason = f"received {job.get('receive_count')} times without completing"
    logger.error("SQS consumer: run %s is a poison message (%s) — dead-lettering", run_id, reason)
    await _mark_failed(run_id, f"Run failed after repeated attempts: {reason}")
    parked = await asyncio.to_thread(send_to_dlq, job.get("body", ""), reason)
    if parked or not os.environ.get("SQS_DLQ_URL"):
        await asyncio.to_thread(delete_job, job["receipt_handle"])  # else keep it: never lose the only copy


async def _mark_failed(run_id: str, message: str) -> None:
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import update as _upd
        async with get_session_factory()() as s:
            await s.execute(_upd(Run).where(Run.id == run_id).values(status="failed", message=message))
            await s.commit()
    except Exception as db_exc:
        logger.warning("SQS consumer: could not mark run %s as failed in DB: %s", run_id, db_exc)


async def _execute_job(run_id: str, params: Dict[str, Any], receipt_handle: str) -> None:
    """Execute a single pipeline job from SQS, then ack the message."""
    from aether_os.core.queue.sqs_client import delete_job, change_visibility
    from aether_os.orchestrator.factory_pipeline import get_factory
    from aether_os.core.council import PreFlightCouncil

    factory = get_factory()
    raw_input = params.get("raw_input", "")
    domain = params.get("domain", "general")
    org_id = params.get("org_id", "")
    client_id = params.get("client_id", "")

    # Heartbeat task — extends visibility timeout every 10 minutes so the
    # message doesn't re-appear while a long pipeline run is in progress.
    heartbeat_task: Optional[asyncio.Task] = None

    async def _heartbeat():
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            await asyncio.to_thread(change_visibility, receipt_handle, 3600)  # boto3 is blocking
            logger.debug("SQS consumer: extended visibility for run %s", run_id)

    try:
        heartbeat_task = asyncio.create_task(_heartbeat())

        # Pre-flight council check
        preflight = {"passed": True, "score": 1.0, "reason": "skipped", "suggestions": []}
        try:
            council = PreFlightCouncil()
            preflight = await asyncio.wait_for(
                council.run(raw_input=raw_input, domain=domain, org_id=org_id),
                timeout=60.0,
            )
        except Exception as ce:
            logger.warning("SQS consumer: PreFlightCouncil skipped: %s", type(ce).__name__)

        await factory.run(
            client_id=client_id,
            raw_input=raw_input,
            domain=domain,
            project_name=params.get("project_name"),
            run_id=run_id,
            org_id=org_id,
            org_slug=params.get("org_slug"),
            council_preflight=preflight,
            github_url=params.get("github_url"),
            designer_spec=params.get("designer_spec") or {},
            tech_preferences=params.get("tech_preferences"),
            model_preference=params.get("model_preference"),
            priority=params.get("priority"),
            codebase_mode=params.get("codebase_mode"),
            existing_schema=params.get("existing_schema"),
        )
        logger.info("SQS consumer: run %s completed — deleting message", run_id)
        await asyncio.to_thread(delete_job, receipt_handle)

    except Exception as exc:
        logger.error("SQS consumer: run %s failed: %s", run_id, exc)
        # Do NOT delete — the message reappears after the visibility timeout for a retry;
        # after MAX_RECEIVES deliveries _park_poison dead-letters it.
        await _mark_failed(run_id, str(exc))
    finally:
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()


async def _mark_running(run_id: str) -> None:
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import update as _upd
        async with get_session_factory()() as s:
            await s.execute(_upd(Run).where(Run.id == run_id).values(status="running"))
            await s.commit()
    except Exception as db_exc:
        logger.warning("SQS consumer: DB status update failed: %s", db_exc)


async def _run_slot(job: Dict[str, Any], cls: str) -> None:
    """Run a job that already holds one run slot and one slot of its class pool; free both when done."""
    try:
        await _execute_job(job["run_id"], job["params"], job["receipt_handle"])
    finally:
        _pools[cls].release()
        _slots.release()


async def _run_when_class_has_room(job: Dict[str, Any], cls: str) -> None:
    """The class pool was full when this job arrived: wait for it WITHOUT holding a run slot (so other classes keep
    flowing), then take both slots and run. The message stays invisible meanwhile; after WAIT_LIMIT_S it goes back."""
    global _waiting
    _waiting += 1
    try:
        try:
            await asyncio.wait_for(_pools[cls].acquire(), WAIT_LIMIT_S)
        except asyncio.TimeoutError:
            from aether_os.core.queue.sqs_client import change_visibility
            await asyncio.to_thread(change_visibility, job["receipt_handle"], 0)
            logger.warning("SQS consumer: run %s waited %ds for the %s pool - returned to the queue", job["run_id"], WAIT_LIMIT_S, cls)
            return
        try:
            await _slots.acquire()
        except BaseException:
            _pools[cls].release()
            raise
    finally:
        _waiting -= 1
    await _mark_running(job["run_id"])
    await _run_slot(job, cls)


async def _poll_loop() -> None:
    """Long-polls SQS; never holds more than _max_inflight() jobs (a slot is taken BEFORE receiving,
    so a busy node leaves messages on the queue for other nodes instead of hoarding them)."""
    from aether_os.core.queue.sqs_client import receive_jobs, is_enabled
    global _slots

    _slots = asyncio.Semaphore(_max_inflight())
    _pools.clear()
    _pools.update({c: asyncio.Semaphore(n) for c, n in class_limits().items()})
    logger.info("SQS pipeline consumer started (max in flight %d, pools %s)", _max_inflight(), class_limits())
    while _RUNNING:
        if not is_enabled():
            await asyncio.sleep(30)
            continue
        if _waiting >= _max_waiting():      # enough parked jobs: leave the rest on the queue for other nodes
            await asyncio.sleep(2)
            continue
        await _slots.acquire()
        handed_off = False
        try:
            jobs = await asyncio.to_thread(receive_jobs, 1, 20)
            for job in jobs:
                run_id = job["run_id"]
                if not run_id:
                    logger.warning("SQS consumer: received job with no run_id, skipping")
                    continue
                if job.get("receive_count", 1) > MAX_RECEIVES:
                    await _park_poison(job)
                    continue
                logger.info("SQS consumer: picked up run %s (delivery %s)", run_id, job.get("receive_count", 1))
                cls = job_class(job["params"])
                if _pools[cls].locked():
                    task = asyncio.create_task(_run_when_class_has_room(job, cls))
                else:
                    await _pools[cls].acquire()           # not locked: returns at once
                    await _mark_running(run_id)
                    task = asyncio.create_task(_run_slot(job, cls))
                    handed_off = True
                _inflight.add(task)
                task.add_done_callback(_inflight.discard)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("SQS consumer poll error: %s", exc)
            await asyncio.sleep(5)  # back-off on error
        finally:
            if not handed_off:
                _slots.release()

    logger.info("SQS pipeline consumer stopped")


def start_consumer() -> None:
    """Start the SQS consumer background task. Called once at server startup."""
    global _CONSUMER_TASK, _RUNNING
    from aether_os.core.queue.sqs_client import is_enabled
    if not is_enabled():
        logger.debug("SQS_QUEUE_URL not set — consumer not started")
        return
    if _CONSUMER_TASK and not _CONSUMER_TASK.done():
        return
    _RUNNING = True
    _CONSUMER_TASK = asyncio.create_task(_poll_loop())
    logger.info("SQS pipeline consumer task created")


def stop_consumer() -> None:
    global _RUNNING, _CONSUMER_TASK
    _RUNNING = False
    if _CONSUMER_TASK and not _CONSUMER_TASK.done():
        _CONSUMER_TASK.cancel()
