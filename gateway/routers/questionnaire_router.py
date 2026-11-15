"""
AetherOS — Interactive Questionnaire Router

Public endpoints (no auth — used by external respondents via shareable link):
  GET  /questionnaire/{token}         — render questionnaire page (HTML or JSON)
  POST /questionnaire/{token}/submit  — submit answers
  GET  /questionnaire/{token}/status  — check completion status

Authenticated endpoints (agency / internal use):
  GET  /runs/{run_id}/questionnaires         — list all sessions for a run
  POST /runs/{run_id}/questionnaire/send     — create session + email link
  POST /runs/{run_id}/questionnaire/fill     — agency fills on behalf of client
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, update

from aether_os.core.db import get_session_factory
from aether_os.core.models import QuestionnaireSession, Run
from aether_os.core.questionnaire.renderer import STAGE_LABELS, render_questionnaire_page
from aether_os.core.questionnaire.stage_questions import get_stage_questions
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.policy_guard import enforce
from aether_os.gateway.routers.questionnaire_helpers import (
    _send_email_via_sendgrid,
    _signal_pipeline_resume,
    validate_required_answers,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["questionnaire"])

_TOKEN_TTL_DAYS = 7


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _get_session_by_token(token: str, db) -> QuestionnaireSession:
    """Look up a QuestionnaireSession by access_token. Raises 404 if missing."""
    qs = (await db.execute(
        select(QuestionnaireSession).where(QuestionnaireSession.access_token == token)
    )).scalar_one_or_none()
    if not qs:
        raise HTTPException(status_code=404, detail="Link not found or expired")
    return qs


async def _verify_run_ownership(run_id: str, user: Dict[str, Any], db) -> Run:
    """Confirm the run belongs to the authenticated user's org. Raises 403 otherwise."""
    run = (await db.execute(
        select(Run).where(Run.id == run_id)
    )).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    org_id = user.get("org_id")
    # Fail closed: a caller without an org, or a run without one, must not pass.
    if not org_id or not run.org_id or run.org_id != org_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return run


def _is_expired(qs: QuestionnaireSession) -> bool:
    expires = qs.token_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return _now_utc() > expires


def _build_share_url(token: str, request: Request | None = None) -> str:
    # Behind nginx request.base_url is the internal address, so the configured public origin comes first.
    base = os.environ.get("APP_BASE_URL", "").rstrip("/")
    if not base and request:
        base = str(request.base_url).rstrip("/")
    if base:
        return f"{base}/api/questionnaire/{token}"
    return f"/api/questionnaire/{token}"


# ── Public endpoints ──────────────────────────────────────────────────────────

# Public endpoint — no auth required: external respondents access via shareable link
@router.get("/questionnaire/{token}", response_class=HTMLResponse)
async def get_questionnaire(token: str, request: Request):
    """Render questionnaire page (HTML) or return JSON for API consumers."""
    sf = get_session_factory()
    async with sf() as db:
        qs = (await db.execute(
            select(QuestionnaireSession).where(QuestionnaireSession.access_token == token)
        )).scalar_one_or_none()
        if not qs or _is_expired(qs):
            accept = request.headers.get("Accept", "")
            if "text/html" in accept:
                return HTMLResponse(
                    "<html><body><h2>This link has expired or is invalid.</h2></body></html>",
                    status_code=404,
                )
            return JSONResponse({"error": "Link not found or expired"}, status_code=404)

        submitted_at_str: str | None = None
        if qs.submitted_at:
            st = qs.submitted_at
            if st.tzinfo is None:
                st = st.replace(tzinfo=timezone.utc)
            submitted_at_str = st.strftime("%B %d, %Y at %H:%M UTC")

        accept = request.headers.get("Accept", "")
        if "application/json" in accept and "text/html" not in accept:
            return JSONResponse({
                "session_id": qs.id,
                "stage_id": qs.stage_id,
                "status": qs.status,
                "questions": qs.questions,
                "submitted_at": submitted_at_str,
            })

        # HTML render
        html = render_questionnaire_page(
            session_id=qs.id,
            stage_id=qs.stage_id,
            questions=qs.questions,
            agency_name=qs.agency_name,
            agency_logo_url=qs.agency_logo_url,
            token=token,
            already_submitted=(qs.status == "completed"),
            submitted_at=submitted_at_str,
        )
        return HTMLResponse(html)


# Public endpoint — no auth required: called by the HTML form via Fetch API
@router.post("/questionnaire/{token}/submit")
async def submit_questionnaire(token: str, body: Dict[str, Any]):
    """Accept answers, validate, save, and signal pipeline to resume."""
    sf = get_session_factory()
    async with sf() as db:
        qs = (await db.execute(
            select(QuestionnaireSession).where(QuestionnaireSession.access_token == token)
        )).scalar_one_or_none()
        if not qs:
            raise HTTPException(status_code=404, detail="Link not found or expired")
        if _is_expired(qs):
            raise HTTPException(status_code=422, detail="This link has expired")
        if qs.status == "completed":
            raise HTTPException(status_code=422, detail="Already submitted")

        answers = body.get("answers") or {}
        errors = validate_required_answers(qs.questions, answers)
        if errors:
            raise HTTPException(status_code=422, detail="; ".join(errors))

        now = _now_utc()
        await db.execute(
            update(QuestionnaireSession)
            .where(QuestionnaireSession.id == qs.id)
            .values(
                answers=answers,
                status="completed",
                submitted_at=now,
            )
        )
        await db.commit()

    # Signal pipeline outside the DB session — failure here is non-fatal
    await _signal_pipeline_resume(qs.run_id, qs.stage_id, answers)
    return {"status": "ok", "message": "Thank you. Your responses have been saved."}


# Public endpoint — no auth required: polling by pipeline / client
@router.get("/questionnaire/{token}/status")
async def questionnaire_status(token: str):
    """Return completion status for polling."""
    sf = get_session_factory()
    async with sf() as db:
        qs = (await db.execute(
            select(QuestionnaireSession).where(QuestionnaireSession.access_token == token)
        )).scalar_one_or_none()
        if not qs:
            raise HTTPException(status_code=404, detail="Link not found or expired")
        submitted_at_str: str | None = None
        if qs.submitted_at:
            st = qs.submitted_at
            if st.tzinfo is None:
                st = st.replace(tzinfo=timezone.utc)
            submitted_at_str = st.isoformat()
        return {
            "status": qs.status,
            "stage_id": qs.stage_id,
            "submitted_at": submitted_at_str,
        }


# ── Authenticated endpoints ───────────────────────────────────────────────────
# Members and above only: the list carries the respondents' access links, and send/fill email people and
# resume the run. A viewer reads the run, never the links.

@router.get("/questionnaire-stages")
async def questionnaire_stages(user: Dict[str, Any] = Depends(get_current_user)):
    """The stages and their questions, so a client can build the fill-on-behalf form."""
    await enforce("questionnaire.manage", user)
    return [{"id": sid, "label": label, "questions": get_stage_questions(sid)} for sid, label in STAGE_LABELS.items()]


@router.get("/runs/{run_id}/questionnaires")
async def list_questionnaires(
    run_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """List all questionnaire sessions for a run, newest first."""
    await enforce("questionnaire.manage", user)
    sf = get_session_factory()
    async with sf() as db:
        await _verify_run_ownership(run_id, user, db)
        rows = (await db.execute(
            select(QuestionnaireSession)
            .where(QuestionnaireSession.run_id == run_id)
            .order_by(QuestionnaireSession.created_at.desc())
        )).scalars().all()
        return [
            {
                "id": r.id,
                "stage_id": r.stage_id,
                "status": r.status,
                "respondent_email": r.respondent_email,
                "respondent_name": r.respondent_name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
                "expires_at": r.token_expires_at.isoformat() if r.token_expires_at else None,
                "share_url": f"/api/questionnaire/{r.access_token}",
            }
            for r in rows
        ]


@router.post("/runs/{run_id}/questionnaire/send")
async def send_questionnaire(
    run_id: str,
    body: Dict[str, Any],
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Create a QuestionnaireSession and send email link to the respondent.

    Body fields:
      stage_id:         str
      respondent_email: str
      respondent_name:  str
      agency_name:      str | None
      agency_logo_url:  str | None
    """
    await enforce("questionnaire.manage", user)
    stage_id = body.get("stage_id", "")
    respondent_email = body.get("respondent_email", "")
    respondent_name = body.get("respondent_name", "")
    agency_name = body.get("agency_name") or None
    agency_logo_url = body.get("agency_logo_url") or None

    if not stage_id:
        raise HTTPException(status_code=422, detail="stage_id is required")
    if stage_id not in STAGE_LABELS:
        raise HTTPException(status_code=422, detail="unknown stage_id")
    if not respondent_email or "@" not in respondent_email or len(respondent_email) > 320:
        raise HTTPException(status_code=422, detail="respondent_email must be an email address")

    questions = get_stage_questions(stage_id)
    token = secrets.token_urlsafe(32)
    expires_at = _now_utc() + timedelta(days=_TOKEN_TTL_DAYS)

    sf = get_session_factory()
    async with sf() as db:
        await _verify_run_ownership(run_id, user, db)
        qs = QuestionnaireSession(
            run_id=run_id,
            stage_id=stage_id,
            status="sent",
            access_token=token,
            token_expires_at=expires_at,
            respondent_email=respondent_email,
            respondent_name=respondent_name,
            agency_name=agency_name,
            agency_logo_url=agency_logo_url,
            questions=questions,
        )
        db.add(qs)
        await db.commit()

    share_url = _build_share_url(token, request)
    logger.info("[questionnaire] share link: /questionnaire/%s (stage=%s, run=%s)", token, stage_id, run_id)

    stage_label = STAGE_LABELS.get(stage_id, stage_id)
    email_sent = await _send_email_via_sendgrid(
        to_email=respondent_email,
        to_name=respondent_name,
        agency_name=agency_name,
        share_url=share_url,
        stage_label=stage_label,
        expires_at=expires_at,
    )
    if not email_sent:
        logger.info(
            "[questionnaire] Email not sent (SENDGRID_API_KEY not configured). Share URL: %s",
            share_url,
        )

    return {
        "session_id": qs.id,
        "share_url": share_url,
        "expires_at": expires_at.isoformat(),
        "email_sent": email_sent,
    }


@router.post("/runs/{run_id}/questionnaire/fill")
async def fill_questionnaire(
    run_id: str,
    body: Dict[str, Any],
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Agency fills questionnaire on behalf of the client (no email link needed).

    Body fields:
      stage_id: str
      answers:  dict
    """
    await enforce("questionnaire.manage", user)
    stage_id = body.get("stage_id", "")
    answers = body.get("answers") or {}
    if not stage_id:
        raise HTTPException(status_code=422, detail="stage_id is required")
    if stage_id not in STAGE_LABELS:
        raise HTTPException(status_code=422, detail="unknown stage_id")

    questions = get_stage_questions(stage_id)
    errors = validate_required_answers(questions, answers)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))

    token = secrets.token_urlsafe(32)
    expires_at = _now_utc() + timedelta(days=_TOKEN_TTL_DAYS)
    now = _now_utc()

    sf = get_session_factory()
    async with sf() as db:
        await _verify_run_ownership(run_id, user, db)
        qs = QuestionnaireSession(
            run_id=run_id,
            stage_id=stage_id,
            status="completed",
            access_token=token,
            token_expires_at=expires_at,
            questions=questions,
            answers=answers,
            submitted_at=now,
        )
        db.add(qs)
        await db.commit()

    await _signal_pipeline_resume(run_id, stage_id, answers)
    logger.info("[questionnaire] agency fill: run=%s stage=%s", run_id, stage_id)
    return {"status": "ok", "session_id": qs.id}
