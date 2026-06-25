"""
Slack notification provider for DCSP.
Uses Block Kit to send rich messages to a Slack webhook.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any
from src.notifications.base import BaseNotifier, NotificationEvent


class SlackNotifier(BaseNotifier):
    """Sends rich notifications to Slack via webhooks."""

    def __init__(self, webhook_url: str = "") -> None:
        self.webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")

    def send(self, event: NotificationEvent) -> bool:
        """Builds and sends a Slack Block Kit message."""
        if not self.webhook_url:
            print("WARNING: SLACK_WEBHOOK_URL not configured, skipping notification")
            return False

        try:
            # 1. Build Header
            if event.status == "success":
                title = "✅ DCSP Repair Success"
            elif event.status == "escalated":
                title = "⚠️ DCSP Escalation Required"
            else:
                title = "❌ DCSP Repair Failed"

            blocks: list[dict[str, Any]] = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": title}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Repo:* {event.repo_name}"},
                        {"type": "mrkdwn", "text": f"*Branch:* {event.branch}"},
                        {"type": "mrkdwn", "text": f"*Confidence:* {event.confidence:.2f}"},
                        {"type": "mrkdwn", "text": f"*Source:* {event.source.upper()}"}
                    ]
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Explanation:*\n{event.explanation}"}
                }
            ]

            # 2. Add Contextual Notes
            if event.source == "memory":
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "♻ *Reused from memory*"}]
                })

            # 3. Add Actions
            if event.pr_url:
                blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View PR"},
                            "url": event.pr_url,
                            "style": "primary"
                        }
                    ]
                })

            # 4. Footer
            if event.fingerprint:
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "plain_text", "text": f"FP: {event.fingerprint}"}]
                })

            # Send request
            payload = {"blocks": blocks}
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200

        except Exception as e:
            print(f"ERROR: Failed to send Slack notification: {e}")
            return False

    def format_message(self, event: NotificationEvent) -> str:
        return super().format_message(event)
