"""
AetherOS — Factory Run Streaming Router

Routes (SSE / streaming):
  POST /factory/runs/{run_id}/sse-token
  GET  /factory/runs/{run_id}/stream
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from aether_os.gateway.dependencies import get_current_user, require_run_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["run-streaming"])

POLL_S = 2.0              # max wait for a pub/sub wake-up before re-reading the history list
KEEPALIVE_S = 15.0        # comment line when idle: proxies/LBs drop silent connections
MAX_STREAM_S = 4 * 3600   # hard cap per connection; the client reconnects with Last-Event-ID
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "error", "timeout"}


# ── Auth helper ────────────────────────────────────────────────────────────────

def _current_user():
    return Depends(get_current_user)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/factory/runs/{run_id}/sse-token")
async def get_sse_token(
    run_id: str,
    user: Dict[str, Any] = Depends(require_run_user),
) -> Dict[str, str]:
    """Exchange bearer JWT for a short-lived (30s) SSE-only token for this run."""
    import secrets
    from aether_os.gateway.auth_refresh import sse_token_set

    sse_tok = secrets.token_urlsafe(32)
    await sse_token_set(sse_tok, org_id=user["org_id"], run_id=run_id)
    return {"sse_token": sse_tok}


@router.get("/factory/runs/{run_id}/stream")
async def stream_run_events(
    run_id: str,
    request: Request,
    sse_token: Optional[str] = None,
    last_event_id: Optional[str] = None,
):
    """Server-Sent Events stream for live pipeline output.

    Auth: POST /factory/runs/{run_id}/sse-token first, then use the
    returned sse_token as a query param here. JWTs must never be passed
    in URLs (they land in nginx/proxy logs).

    Fix 21: Accepts Last-Event-ID header to resume from a specific position
    so reconnects do not replay all events from the beginning.
    """
    from aether_os.core.audit.ledger import get_ledger
    from aether_os.gateway.auth_refresh import sse_token_pop

    if not sse_token:
        return Response(
            status_code=401,
            content="sse_token required — POST /factory/runs/{run_id}/sse-token first",
        )

    entry = await sse_token_pop(sse_token)
    if not entry or entry.get("run_id") != run_id:
        return Response(status_code=401, content="SSE token invalid or expired")

    org_id = entry["org_id"]
    if not org_id:
        return Response(status_code=401, content="Invalid token")

    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        return Response(status_code=404, content="Run not found or access denied")

    # Fix 21: parse Last-Event-ID — browsers send this as a header on reconnect (HTML5 EventSource
    # spec). Also accept the query param as a fallback for non-browser clients.
    _last_seen = -1
    _header_lei = request.headers.get("Last-Event-ID") or request.headers.get("last-event-id")
    _raw_lei = _header_lei if _header_lei is not None else last_event_id
    if _raw_lei is not None:
        try:
            _last_seen = int(_raw_lei)
        except (ValueError, TypeError):
            _last_seen = -1

    async def event_generator():
        from aether_os.core.pipeline_state import get_redis, get_event_history, _local_history

        # Fix 21: replay only events after last_seen position
        history = await get_event_history(run_id)
        # Fix 22: check decisions table for spec_review_ready events before replaying
        _decided_ids: set = set()
        try:
            from aether_os.core.decisions.decision_engine import get_decision_engine as _gde
            _engine = _gde()
            _decisions = await _engine.list_for_run(run_id, status=None)
            _decided_ids = {
                d.id for d in _decisions
                if getattr(d, "status", None) in ("approved", "rejected")
            }
        except Exception as exc:
            logger.debug(
                "Failed to load existing decisions for SSE replay (run %s): %s", run_id, exc
            )

        replay_start = _last_seen + 1
        for idx, past_event in enumerate(history[replay_start:], start=replay_start):
            # Fix 22: swap spec_review_ready for decision_already_made if already decided
            _etype = past_event.get("type", "")
            if _etype in ("spec_review_ready", "PhaseApprovalRequired"):
                _did = past_event.get("decision_id")
                if _did and _did in _decided_ids:
                    past_event = {**past_event, "type": "decision_already_made", "original_type": _etype}
            yield f"id: {idx}\ndata: {json.dumps(past_event)}\n\n"

        r = await get_redis()
        if r is None:
            # Redis unavailable — poll the in-process _local_history buffer.
            # The pipeline writes to _local_history when Redis is down, so we
            # tail it here rather than abandoning the stream.
            seen = len(history)
            _idle = 0
            _deadline = asyncio.get_event_loop().time() + 1800  # 30-min hard timeout
            while True:
                if asyncio.get_event_loop().time() > _deadline:
                    yield f"data: {json.dumps({'type': 'stream_timeout', 'message': 'SSE fallback stream timed out after 30 minutes'})}\n\n"
                    return
                buf = _local_history.get(run_id, [])
                for raw in buf[seen:]:
                    seen += 1
                    yield f"id: {seen - 1}\ndata: {raw}\n\n"
                    try:
                        if json.loads(raw).get("type") == "pipeline_complete":
                            return
                    except Exception as exc:
                        logger.debug(
                            "Failed to parse SSE event from local history buffer: %s", exc
                        )
                if await request.is_disconnected():
                    return
                _idle += 1
                if _idle % 30 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.5)
            return

        # The history list is the source of truth (indexed, so no gap and no duplicate); pub/sub only
        # wakes us early. Events published between the replay read and the subscribe are in the list
        # too, so re-reading it from our position on every wake-up and every POLL_S misses nothing.
        key = f"pipeline:history:{run_id}"
        channel = f"pipeline:events:{run_id}"
        pubsub = r.pubsub()
        try:
            await pubsub.subscribe(channel)
            next_idx = len(history)
            if any(e.get("type") == "pipeline_complete" for e in history):
                return  # finished run: replay, then close instead of idling forever
            loop = asyncio.get_running_loop()
            last_sent = loop.time()
            deadline = loop.time() + MAX_STREAM_S
            while loop.time() < deadline:
                if await request.is_disconnected():
                    return
                await pubsub.get_message(ignore_subscribe_messages=True, timeout=POLL_S)
                for raw in await r.lrange(key, next_idx, -1):
                    try:
                        event = json.loads(raw)
                    except Exception as exc:
                        logger.debug("Unparseable history entry for run %s: %s", run_id, exc)
                        event = None
                    if event is not None:
                        _etype = event.get("type", "")
                        _did = event.get("decision_id")
                        if _etype in ("spec_review_ready", "PhaseApprovalRequired") and _did and _did in _decided_ids:
                            event = {**event, "type": "decision_already_made", "original_type": _etype}
                        yield f"id: {next_idx}\ndata: {json.dumps(event)}\n\n"
                        last_sent = loop.time()
                        if event.get("type") == "pipeline_complete":
                            return
                    next_idx += 1
                if loop.time() - last_sent >= KEEPALIVE_S:
                    yield ": keepalive\n\n"   # keeps proxies from closing an idle stream
                    last_sent = loop.time()
                    run = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
                    if run and run.get("status") in TERMINAL_STATUSES:
                        yield f"data: {json.dumps({'type': 'stream_end', 'status': run.get('status')})}\n\n"
                        return  # run finished but its completion event was lost: do not hang
            yield f"data: {json.dumps({'type': 'stream_timeout', 'message': 'stream limit reached; reconnect with Last-Event-ID'})}\n\n"
        except Exception as _sse_exc:
            logger.warning("SSE Redis stream error for run %s: %s", run_id, _sse_exc)
            yield f"data: {json.dumps({'type': 'stream_error', 'message': 'SSE connection lost; please reconnect'})}\n\n"
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception as exc:
                logger.debug("SSE pubsub cleanup failed for run %s: %s", run_id, exc)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
