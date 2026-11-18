"""Guided-mode questionnaire pause / poll (moved verbatim from factory_pipeline, KAN-57)."""
from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select as _sel, update as _upd

from aether_os.core.db import get_session_factory as _gsf_q
from aether_os.core.models import QuestionnaireSession, Run
from aether_os.core.questionnaire.stage_questions import get_stage_questions

logger = logging.getLogger(__name__)


async def _pause_for_questionnaire(
    run_id: str,
    stage_id: str,
    stage_result: dict,
    accumulated_context: dict,
    sem: Optional[asyncio.Semaphore] = None,
) -> None:
    """Create a QuestionnaireSession for this stage and poll until completed or expired.

    Called from _execute_pipeline when mode == "guided".  Sets the run status to
    "waiting_for_input" so the frontend can show a waiting state, then polls the
    DB every 30 seconds.  On completion, merges answers into accumulated_context.
    Timeout: 7 days (604800 s) — matches the default token TTL.

    H1 — semaphore release during wait: if *sem* is provided, the pipeline
    concurrency slot is released before each sleep interval and re-acquired
    after.  This prevents guided-mode runs from holding a concurrency slot for
    up to 7 days and starving all other pipeline users.
    """
    try:

        _TOKEN_TTL_DAYS = 7
        _POLL_INTERVAL = 30          # seconds between DB polls
        _MAX_WAIT = 604800           # 7 days in seconds

        questions = get_stage_questions(stage_id)
        if not questions:
            # No questions for this stage — skip the pause
            logger.debug(
                "questionnaire: no questions for stage %s, skipping pause (run=%s)",
                stage_id, run_id,
            )
            return

        _sf = _gsf_q()
        # Check if a session already exists for this run + stage
        async with _sf() as _db:
            existing = (await _db.execute(
                _sel(QuestionnaireSession)
                .where(
                    QuestionnaireSession.run_id == run_id,
                    QuestionnaireSession.stage_id == stage_id,
                )
            )).scalar_one_or_none()

            if existing and existing.status == "completed":
                # Already answered — merge and move on immediately
                if existing.answers:
                    qs_answers = accumulated_context.get("questionnaire_answers", {})
                    qs_answers[stage_id] = existing.answers
                    accumulated_context["questionnaire_answers"] = qs_answers
                logger.info(
                    "questionnaire: stage %s already completed for run %s — continuing",
                    stage_id, run_id,
                )
                return

            if not existing:
                # Create session with the agency branding from accumulated_context
                token = secrets.token_urlsafe(32)
                expires_at = datetime.now(timezone.utc) + timedelta(days=_TOKEN_TTL_DAYS)
                _qs = QuestionnaireSession(
                    run_id=run_id,
                    stage_id=stage_id,
                    status="pending",
                    access_token=token,
                    token_expires_at=expires_at,
                    respondent_email=accumulated_context.get("respondent_email") or None,
                    agency_name=accumulated_context.get("agency_name") or None,
                    agency_logo_url=accumulated_context.get("agency_logo_url") or None,
                    questions=questions,
                )
                _db.add(_qs)
                await _db.commit()
                session_id = _qs.id
                logger.info(
                    "[questionnaire] share link: /questionnaire/%s (stage=%s, run=%s)",
                    token, stage_id, run_id,
                )
            else:
                session_id = existing.id

            # Set run status to waiting_for_input
            await _db.execute(
                _upd(Run).where(Run.id == run_id).values(status="waiting_for_input")
            )
            await _db.commit()

        # ── Polling loop ────────────────────────────────────────────────────
        waited = 0
        while waited < _MAX_WAIT:
            logger.debug(
                "questionnaire: waiting for stage %s input (run %s, waited=%ds)",
                stage_id, run_id, waited,
            )
            # H1: Release the pipeline concurrency slot during the sleep so
            # other users' runs are not blocked while we wait for questionnaire
            # input (which can take up to 7 days).  Re-acquire after waking.
            if sem is not None:
                sem.release()
            try:
                await asyncio.sleep(_POLL_INTERVAL)
                waited += _POLL_INTERVAL
            finally:
                if sem is not None:
                    await sem.acquire()

            async with _sf() as _db_poll:
                row = (await _db_poll.execute(
                    _sel(QuestionnaireSession).where(QuestionnaireSession.id == session_id)
                )).scalar_one_or_none()

                if not row:
                    logger.warning(
                        "questionnaire: session %s disappeared — resuming without answers",
                        session_id,
                    )
                    break

                if row.status == "completed":
                    if row.answers:
                        qs_answers = accumulated_context.get("questionnaire_answers", {})
                        qs_answers[stage_id] = row.answers
                        accumulated_context["questionnaire_answers"] = qs_answers
                    logger.info(
                        "questionnaire: stage %s completed for run %s — pipeline resuming",
                        stage_id, run_id,
                    )
                    # Restore run status to running
                    await _db_poll.execute(
                        _upd(Run).where(Run.id == run_id).values(status="running")
                    )
                    await _db_poll.commit()
                    return

                # Check for expiry
                expires = row.token_expires_at
                if expires:
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) > expires:
                        await _db_poll.execute(
                            _upd(QuestionnaireSession)
                            .where(QuestionnaireSession.id == session_id)
                            .values(status="expired")
                        )
                        await _db_poll.commit()
                        logger.warning(
                            "questionnaire: session %s expired for run %s — resuming without answers",
                            session_id, run_id,
                        )
                        break

        # Timed out or expired — set run back to running so pipeline continues
        try:
            async with _sf() as _db_end:
                await _db_end.execute(
                    _upd(Run).where(Run.id == run_id).values(status="running")
                )
                await _db_end.commit()
        except Exception as _end_exc:
            logger.warning("questionnaire: failed to restore run status: %s", _end_exc)

    except Exception as e:
        logger.warning(
            "questionnaire: _pause_for_questionnaire failed (non-fatal, run=%s stage=%s): %s",
            run_id, stage_id, e,
        )
