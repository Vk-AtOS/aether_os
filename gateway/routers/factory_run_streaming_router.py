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
                await asyncio.sleep(0.5)
            return

        pubsub = r.pubsub()
        await pubsub.subscribe(f"pipeline:events:{run_id}")
        _live_idx = len(history)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    event = json.loads(message["data"])
                except Exception as exc:
                    logger.debug(
                        "Failed to parse SSE Redis pubsub message for run %s: %s", run_id, exc
                    )
                    continue
                # Fix 22: also gate spec_review_ready on live events
                _etype = event.get("type", "")
                if _etype in ("spec_review_ready", "PhaseApprovalRequired"):
                    _did = event.get("decision_id")
                    if _did and _did in _decided_ids:
                        event = {**event, "type": "decision_already_made", "original_type": _etype}
                yield f"id: {_live_idx}\ndata: {json.dumps(event)}\n\n"
                _live_idx += 1
                if event.get("type") == "pipeline_complete":
                    break
        except Exception as _sse_exc:
            logger.warning("SSE Redis pubsub error for run %s: %s", run_id, _sse_exc)
            yield f"data: {json.dumps({'type': 'stream_error', 'message': 'SSE connection lost; please reconnect'})}\n\n"
        finally:
            await pubsub.unsubscribe(f"pipeline:events:{run_id}")
            await pubsub.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
