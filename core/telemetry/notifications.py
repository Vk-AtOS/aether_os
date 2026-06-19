"""
Notification router for DCSP.
Orchestrates multiple notification providers.
"""

from __future__ import annotations

import logging
import os
import threading
from src.notifications.base import BaseNotifier, NotificationEvent
from src.notifications.slack_notifier import SlackNotifier
from src.notifications.email_notifier import EmailNotifier

logger = logging.getLogger(__name__)


class NotificationRouter:
    """Routes events to all configured notification providers."""

    def __init__(self) -> None:
        self.notifiers: list[BaseNotifier] = []
        
        # Auto-configure from environment
        if os.environ.get("SLACK_WEBHOOK_URL"):
            self.add_notifier(SlackNotifier())
        
        if os.environ.get("DCSP_SMTP_HOST"):
            self.add_notifier(EmailNotifier())

    def add_notifier(self, notifier: BaseNotifier) -> None:
        """Adds a provider to the list of active notifiers."""
        self.notifiers.append(notifier)

    def notify(self, event: NotificationEvent) -> dict[str, bool]:
        """Sends notification to all active providers."""
        results = {}
        for notifier in self.notifiers:
            name = notifier.__class__.__name__.lower().replace("notifier", "")
            try:
                results[name] = notifier.send(event)
            except Exception as e:
                logger.error("Notifier %s failed: %s", name, e)
                results[name] = False
        return results


# Global singleton
GLOBAL_NOTIFICATION_ROUTER = NotificationRouter()
