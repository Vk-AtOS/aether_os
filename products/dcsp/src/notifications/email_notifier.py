"""
Email notification provider for DCSP.
Sends plain-text email alerts via SMTP.
"""

from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from src.notifications.base import BaseNotifier, NotificationEvent


class EmailNotifier(BaseNotifier):
    """Sends email notifications via SMTP."""

    def __init__(self, smtp_host: str = "",
                 smtp_port: int = 0,
                 smtp_user: str = "",
                 smtp_password: str = "",
                 from_addr: str = "",
                 to_addrs: list[str] | None = None) -> None:
        self.smtp_host = smtp_host or os.environ.get("DCSP_SMTP_HOST", "")
        self.smtp_port = smtp_port or int(os.environ.get("DCSP_SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.environ.get("DCSP_SMTP_USER", "")
        self.smtp_password = smtp_password or os.environ.get("DCSP_SMTP_PASSWORD", "")
        self.from_addr = from_addr or os.environ.get("DCSP_ALERT_FROM", "dcsp@example.com")
        
        if to_addrs is None:
            to_str = os.environ.get("DCSP_ALERT_TO", "")
            self.to_addrs = [a.strip() for d in to_str.split(",") if (a := d.strip())]
        else:
            self.to_addrs = to_addrs

    def send(self, event: NotificationEvent) -> bool:
        """Builds and sends a plain-text email."""
        if not self.smtp_host or not self.to_addrs:
            print("WARNING: SMTP not configured correctly, skipping notification")
            return False

        try:
            subject = f"[DCSP] {event.status.upper()}: {event.repo_name} ({event.branch})"
            
            body_parts = [
                f"Status: {event.status.upper()}",
                f"Repository: {event.repo_name}",
                f"Branch: {event.branch}",
                f"Confidence: {event.confidence:.2f}",
                f"Source: {event.source}",
                "",
                "Explanation:",
                event.explanation,
                ""
            ]

            if event.patch_diff:
                body_parts.append("Patch Preview:")
                body_parts.append(event.patch_diff[:300] + ("..." if len(event.patch_diff) > 300 else ""))
                body_parts.append("")

            if event.pr_url:
                body_parts.append(f"View PR: {event.pr_url}")
                body_parts.append("")

            msg = MIMEText("\n".join(body_parts))
            msg["Subject"] = subject
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(self.to_addrs)

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.smtp_user:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            return True

        except Exception as e:
            print(f"ERROR: Failed to send email notification: {e}")
            return False
