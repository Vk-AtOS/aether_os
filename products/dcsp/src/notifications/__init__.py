"""
Notification system for DCSP.
"""

from __future__ import annotations

from src.notifications.base import BaseNotifier, NotificationEvent
from src.notifications.slack_notifier import SlackNotifier
from src.notifications.email_notifier import EmailNotifier
from src.notifications.router import NotificationRouter, GLOBAL_NOTIFICATION_ROUTER

__all__ = [
    "BaseNotifier",
    "NotificationEvent",
    "SlackNotifier",
    "EmailNotifier",
    "NotificationRouter",
    "GLOBAL_NOTIFICATION_ROUTER"
]
