"""
AetherOS — Factory V2 Router  (mounted at /v2/factory/...)

Clean service-layer API: all business logic goes through PipelineService.
No raw DB calls here. Preferred for external integrations and SDK clients.

V1 counterpart: gateway/routers/factory_runs_router.py  (mounted at /factory/...)
V1 is used by the AetherOS dashboard. V2 is the API-consumer surface.
"""
from __future__ import annotations
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/factory", tags=["factory"])


# ── Request/Response models ────────────────────────────────────────────────────

class StartRequest(BaseModel):
    raw_input: str
    project_name: Optional[str] = None
    domain: str = "general"
    client_id: Optional[str] = None
    is_change_request: bool = False
    memory_context: Optional[str] = None


class PriorityRequest(BaseModel):
    priority: str  # "high" | "normal" | "low"


class RerunRequest(BaseModel):
    from_phase: str


class ChangeRequestBody(BaseModel):
    change_description: str
    affected_areas: List[str] = []  # e.g. ["backend", "frontend"]
    client_id: Optional[str] = None


# ── Dependency injection ───────────────────────────────────────────────────────

def _svc():
    from aether_os.core.services.pipeline_service import get_pipeline_service
    return get_pipeline_service()


def _auth():
    from aether_os.gateway.api import get_current_user
    return Depends(get_current_user)


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/start")
async def start_pipeline(
    req: StartRequest,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """Start a new pipeline run."""
    svc = _svc()
    try:
        result = await svc.start_run(
            org_id=user["org_id"],
            org_slug=user.get("org_slug", ""),
            plan=user.get("plan", "trial"),
            raw_input=req.raw_input,
            project_name=req.project_name,
            domain=req.domain,
            client_id=req.client_id,
            is_change_request=req.is_change_request,
            memory_context=req.memory_context,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc))


@router.get("/runs")
async def list_runs(
    user: Dict[str, Any] = _auth(),
) -> List[Dict[str, Any]]:
    """List all pipeline runs for the current organisation."""
    svc = _svc()
    return await svc.list_runs(org_id=user["org_id"])


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """Get full detail for a single run."""
    svc = _svc()
    try:
        return await svc.get_run(run_id=run_id, org_id=user["org_id"])
    except LookupError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/pause")
async def pause_run(
    run_id: str,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, str]:
    svc = _svc()
    try:
        await svc.pause_run(run_id=run_id, org_id=user["org_id"])
        return {"status": "paused"}
    except LookupError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, str]:
    svc = _svc()
    try:
        await svc.resume_run(run_id=run_id, org_id=user["org_id"])
        return {"status": "running"}
    except LookupError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, str]:
    svc = _svc()
    try:
        await svc.cancel_run(run_id=run_id, org_id=user["org_id"])
        return {"status": "cancelled"}
    except LookupError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/priority")
async def set_priority(
    run_id: str,
    req: PriorityRequest,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, str]:
    if req.priority not in ("high", "normal", "low"):
        raise HTTPException(status_code=400, detail="priority must be high, normal, or low")
    svc = _svc()
    try:
        await svc.set_priority(run_id=run_id, org_id=user["org_id"], priority=req.priority)
        return {"priority": req.priority}
    except LookupError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/rerun")
async def rerun_from_phase(
    run_id: str,
    req: RerunRequest,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """Start a new run from a specific phase, copying input from the original."""
    import asyncio, uuid
    svc = _svc()
    try:
        original = await svc.get_run(run_id=run_id, org_id=user["org_id"])
    except LookupError:
        raise HTTPException(status_code=404, detail="Original run not found")

    try:
        result = await svc.start_run(
            org_id=user["org_id"],
            org_slug=user.get("org_slug", ""),
            plan=user.get("plan", "trial"),
            raw_input=original.get("raw_input") or original.get("requirement") or "",
            project_name=original.get("project_name"),
            domain=original.get("domain", "general"),
            client_id=original.get("client_id"),
            is_change_request=False,
        )
        return {**result, "from_phase": req.from_phase}
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc))



@router.post("/projects/{project_id}/change-request")
async def submit_change_request(
    project_id: str,
    req: ChangeRequestBody,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, Any]:
    """Start a partial re-run from the first affected phase for a change request.

    Loads the original project's context so all prior phase outputs remain
    visible to re-run phases. Only phases at or after the first affected area
    are executed.
    """
    from aether_os.orchestrator.factory_pipeline import get_factory
    factory = get_factory()
    import asyncio, uuid
    run_id = str(uuid.uuid4())
    # Register in DB before spawning the task
    try:
        from aether_os.core.db_utils import create_run
        await create_run(
            run_id=run_id,
            command=f"change_request: {req.change_description[:60]}",
            org_id=user["org_id"],
            project_name=f"cr-{project_id[:8]}",
            domain="general",
            client_id=req.client_id,
            raw_input=req.change_description,
        )
    except Exception as exc:
        logger.warning("CR run DB create failed: %s", exc)

    asyncio.create_task(
        factory.run_change_request(
            project_id=project_id,
            client_id=req.client_id or user.get("sub", "operator"),
            change_description=req.change_description,
            affected_areas=req.affected_areas,
            org_id=user["org_id"],
            run_id=run_id,
        )
    )
    return {"run_id": run_id, "status": "started", "project_id": project_id}


# ── SSE streaming ──────────────────────────────────────────────────────────────


@router.post("/runs/{run_id}/sse-token")
async def get_sse_token(
    run_id: str,
    user: Dict[str, Any] = _auth(),
) -> Dict[str, str]:
    """Exchange bearer JWT for a 30-second SSE-only token (keeps JWT out of URL/logs)."""
    import secrets
    from aether_os.core.rate_limiter import sse_token_set
    tok = secrets.token_urlsafe(32)
    await sse_token_set(tok, org_id=user["org_id"], run_id=run_id)
    return {"sse_token": tok}


@router.get("/runs/{run_id}/stream")
async def stream_run_events(
    run_id: str,
    sse_token: Optional[str] = None,
    token: Optional[str] = None,
):
    """SSE stream for live pipeline output. Use sse-token endpoint first."""
    import asyncio, json
    from aether_os.gateway.auth import decode_access_token

    org_id = None
    if sse_token:
        from aether_os.core.rate_limiter import sse_token_pop
        entry = await sse_token_pop(sse_token)
        if entry and entry.get("run_id") == run_id:
            org_id = entry["org_id"]
        else:
            return Response(status_code=401, content="SSE token invalid or expired")
    elif token:
        payload = decode_access_token(token)
        if payload:
            org_id = payload.get("org_id")

    if not org_id:
        return Response(status_code=401, content="Authentication required")

    async def event_generator():
        from aether_os.core.pipeline_state import get_redis, get_event_history
        for past_event in await get_event_history(run_id):
            yield f"data: {json.dumps(past_event)}\n\n"

        r = await get_redis()
        if r is None:
            yield f"data: {json.dumps({'type': 'no_stream', 'run_id': run_id, 'reason': 'redis_unavailable'})}\n\n"
            return

        pubsub = r.pubsub()
        await pubsub.subscribe(f"pipeline:events:{run_id}")
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    event = json.loads(message["data"])
                except Exception:
                    continue
                yield f"data: {message['data']}\n\n"
                if event.get("type") == "pipeline_complete":
                    break
        except Exception:
            pass
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
