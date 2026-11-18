"""
Questionnaire helper functions — split from questionnaire_router.py to keep
that file under 400 lines.  Only imported by questionnaire_router.py.
"""
from __future__ import annotations

import logging
import os
from html import escape
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


async def _signal_pipeline_resume(run_id: str, stage_id: str, answers: dict) -> None:
    """Merge questionnaire answers into run context and flip status back to running.

    The pipeline poller (_pause_for_questionnaire in factory_pipeline.py) detects
    the completed questionnaire_sessions row and continues — this function writes
    the answers into accumulated_context so the next phase can consume them.
    """
    try:
        # Deferred import: avoids circular dependency at module load time.
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Run
        from sqlalchemy import select, update
        sf = get_session_factory()
        async with sf() as session:
            run = (await session.execute(
                select(Run).where(Run.id == run_id)
            )).scalar_one_or_none()
            if not run:
                logger.warning("questionnaire: run %s not found for resume", run_id)
                return
            ctx: dict = run.accumulated_context or {}
            qs_answers = ctx.get("questionnaire_answers", {})
            qs_answers[stage_id] = answers
            ctx["questionnaire_answers"] = qs_answers
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(status="running", accumulated_context=ctx)
            )
            await session.commit()
            logger.info(
                "questionnaire: pipeline resumed for run %s after stage %s",
                run_id, stage_id,
            )
    except Exception as e:
        logger.warning(
            "questionnaire: pipeline resume failed for run %s: %s", run_id, e
        )


async def _send_email_via_sendgrid(
    to_email: str,
    to_name: str,
    agency_name: str | None,
    share_url: str,
    stage_label: str,
    expires_at: datetime,
) -> bool:
    """Send questionnaire link via SendGrid. Returns True on success."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        return False

    from_email = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@aetheros.ai")
    brand = agency_name or "AetherOS"
    expires_str = expires_at.strftime("%B %d, %Y") if expires_at else "7 days"

    body = {
        "personalizations": [
            {
                "to": [{"email": to_email, "name": to_name}],
                "subject": f"{brand} — Your input needed: {stage_label}",
            }
        ],
        "from": {"email": from_email, "name": brand},
        "content": [
            {
                "type": "text/html",
                "value": (
                    f"<p>Hi {escape(to_name or '')},</p>"
                    f"<p>{escape(brand)} needs your input for the <strong>{escape(stage_label)}</strong> stage.</p>"
                    f"<p><a href='{escape(share_url)}' style='padding:12px 24px;background:#6d28d9;"
                    f"color:#fff;border-radius:8px;text-decoration:none;font-weight:bold'>"
                    f"Open questionnaire</a></p>"
                    f"<p>This link expires on {expires_str}.</p>"
                    f"<p style='color:#9ca3af;font-size:12px'>If you did not expect this email, "
                    f"you can safely ignore it.</p>"
                ),
            }
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code not in (200, 202):
                logger.warning(
                    "questionnaire: SendGrid returned %s: %s",
                    resp.status_code, resp.text[:200],
                )
                return False
            return True
    except Exception as e:
        logger.warning("questionnaire: SendGrid send failed: %s", e)
        return False


def validate_required_answers(questions: list[dict], answers: dict) -> list[str]:
    """Return list of human-readable error messages for missing required fields."""
    errors: list[str] = []
    for q in questions:
        if not q.get("required"):
            continue
        val = answers.get(q["id"])
        if val is None or val == "" or val == []:
            errors.append(f"'{q['label']}' is required.")
    return errors
