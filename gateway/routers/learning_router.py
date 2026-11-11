"""
AetherOS — Learning Router
GET  /learning/context
GET  /learning/clarifications
POST /learning/clarifications/{clarification_id}/answer
POST /factory/runs/{run_id}/feedback
GET  /learning/stats
GET  /learning/golden-builds
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from aether_os.gateway.dependencies import get_current_user, require_run_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["learning"])


class FeedbackBody(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    tags: Optional[List[str]] = None
    comment: Optional[str] = None


def _current_user():
    return Depends(get_current_user)


@router.get("/learning/context")
async def get_learning_context(user: Dict[str, Any] = _current_user()):
    """Return learned patterns for the current user (used by pipeline for LLM personalisation)."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.services import learning_service
    sf = get_session_factory()
    async with sf() as session:
        ctx = await learning_service.get_user_context(
            org_id=user["org_id"], user_id=user["user_id"], session=session
        )
    return {"patterns": ctx}


@router.get("/learning/clarifications")
async def get_clarifications(user: Dict[str, Any] = _current_user()):
    """Return pending project-scoped clarification questions for the current user."""
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.services import learning_service
        sf = get_session_factory()
        async with sf() as session:
            questions = await learning_service.get_pending_clarifications(
                org_id=user["org_id"], user_id=user["user_id"], session=session
            )
        return {"clarifications": questions}
    except Exception as e:
        logger.warning("learning_router: get_clarifications failed: %s", e)
        return {"clarifications": []}


@router.post("/learning/clarifications/{clarification_id}/answer")
async def answer_clarification(
    clarification_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """Submit an answer to a pending clarification question."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.services import learning_service
    answer = body.get("answer")
    if not answer:
        raise HTTPException(status_code=400, detail="answer required")
    sf = get_session_factory()
    async with sf() as session:
        ok = await learning_service.answer_clarification(
            clarification_id=clarification_id,
            org_id=user["org_id"],
            user_id=user["user_id"],
            answer=answer,
            session=session,
        )
    if not ok:
        raise HTTPException(status_code=404, detail="Clarification not found or already answered")
    return {"status": "answered"}


@router.post("/factory/runs/{run_id}/feedback")
async def submit_run_feedback(
    run_id: str,
    body: FeedbackBody,
    user: Dict[str, Any] = Depends(require_run_user),
):
    """Submit star rating + optional tags/comment for a completed run."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.learning.golden_retriever import record_feedback
    sf = get_session_factory()
    async with sf() as session:
        result = await record_feedback(
            run_id=run_id,
            org_id=user["org_id"] or "",
            user_id=user.get("user_id"),
            rating=body.rating,
            tags=body.tags,
            comment=body.comment,
            session=session,
        )
    return result


@router.get("/learning/stats")
async def get_learning_stats(user: Dict[str, Any] = _current_user()):
    """Return self-improvement system statistics."""
    from aether_os.core.learning.golden_retriever import get_stats
    return await get_stats()


@router.get("/learning/golden-builds")
async def list_golden_builds(user: Dict[str, Any] = _current_user()):
    """List active golden build examples."""
    from aether_os.core.learning.golden_retriever import get_golden_builds_list
    builds = await get_golden_builds_list(limit=20)
    return {"golden_builds": builds}
