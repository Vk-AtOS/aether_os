"""
AetherOS — Learning Router
GET /learning/context
GET /learning/clarifications
POST /learning/clarifications/{clarification_id}/answer
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(tags=["learning"])


def _current_user():
    from aether_os.gateway.api import get_current_user
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
    from aether_os.core.db import get_session_factory
    from aether_os.core.services import learning_service
    sf = get_session_factory()
    async with sf() as session:
        questions = await learning_service.get_pending_clarifications(
            org_id=user["org_id"], user_id=user["user_id"], session=session
        )
    return {"clarifications": questions}


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
