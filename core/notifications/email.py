"""Email notification dispatcher using SMTP (configurable via env vars).

Environment variables:
    SMTP_HOST       — SMTP server hostname (default: localhost)
    SMTP_PORT       — SMTP port (default: 587)
    SMTP_USER       — SMTP username
    SMTP_PASSWORD   — SMTP password
    SMTP_FROM       — From address (default: noreply@aetheros.ai)
    SMTP_TLS        — Use STARTTLS (default: true)
    EMAIL_ENABLED   — Master switch; set to 'false' to disable (default: true)
"""
from __future__ import annotations
import asyncio
import logging
import os
import smtplib
import email.mime.text
import email.mime.multipart
from typing import Optional

logger = logging.getLogger(__name__)

_instance: Optional["EmailNotifier"] = None


class EmailNotifier:
    def __init__(self) -> None:
        self.host = os.getenv("SMTP_HOST", "localhost")
        self.port = int(os.getenv("SMTP_PORT", "587"))
        self.user = os.getenv("SMTP_USER", "")
        self.password = os.getenv("SMTP_PASSWORD", "")
        self.from_addr = os.getenv("SMTP_FROM", "noreply@aetheros.ai")
        self.use_tls = os.getenv("SMTP_TLS", "true").lower() != "false"
        self.enabled = os.getenv("EMAIL_ENABLED", "true").lower() != "false"

    def _send_sync(self, to: str, subject: str, body_html: str, body_text: str) -> None:
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = to
        msg.attach(email.mime.text.MIMEText(body_text, "plain"))
        msg.attach(email.mime.text.MIMEText(body_html, "html"))
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.sendmail(self.from_addr, [to], msg.as_string())

    async def send(self, to: str, subject: str, body_html: str, body_text: str = "") -> bool:
        if not self.enabled:
            logger.debug("Email disabled — skipping send to %s", to)
            return False
        if not body_text:
            body_text = body_html.replace("<br>", "\n").replace("<p>", "").replace("</p>", "\n")
        try:
            await asyncio.to_thread(self._send_sync, to, subject, body_html, body_text)
            logger.info("Email sent to %s: %s", to, subject)
            return True
        except Exception as exc:
            logger.warning("Email send failed to %s: %s", to, exc)
            return False

    async def notify_run_complete(self, to: str, project_name: str, run_id: str, cost: float, frontend_url: str = "") -> bool:
        url = f"{frontend_url}/project/{run_id}" if frontend_url else f"/project/{run_id}"
        subject = f"✅ AetherOS: {project_name} pipeline completed"
        html = (
            f"<p>Your pipeline <strong>{project_name}</strong> has completed successfully.</p>"
            f"<p>Cost: <strong>${cost:.4f}</strong></p>"
            f"<p><a href='{url}'>View project results →</a></p>"
            f"<hr><p style='color:#888;font-size:12px'>AetherOS Factory</p>"
        )
        return await self.send(to, subject, html)

    async def notify_run_failed(self, to: str, project_name: str, run_id: str, frontend_url: str = "") -> bool:
        url = f"{frontend_url}/project/{run_id}" if frontend_url else f"/project/{run_id}"
        subject = f"❌ AetherOS: {project_name} pipeline failed"
        html = (
            f"<p>Your pipeline <strong>{project_name}</strong> encountered an error and could not complete.</p>"
            f"<p><a href='{url}'>View error details →</a></p>"
            f"<hr><p style='color:#888;font-size:12px'>AetherOS Factory</p>"
        )
        return await self.send(to, subject, html)

    async def notify_decision_required(self, to: str, project_name: str, run_id: str, phase: str, frontend_url: str = "") -> bool:
        url = f"{frontend_url}/project/{run_id}" if frontend_url else f"/project/{run_id}"
        subject = f"⚠️ AetherOS: Decision required — {project_name}"
        html = (
            f"<p>Pipeline <strong>{project_name}</strong> requires your approval at phase <strong>{phase}</strong>.</p>"
            f"<p><a href='{url}'>Review and decide →</a></p>"
            f"<hr><p style='color:#888;font-size:12px'>AetherOS Factory</p>"
        )
        return await self.send(to, subject, html)


def get_email_notifier() -> EmailNotifier:
    global _instance
    if _instance is None:
        _instance = EmailNotifier()
    return _instance
