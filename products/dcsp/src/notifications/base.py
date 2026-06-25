"""
Base classes for DCSP notifications.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class NotificationEvent:
    """Standardized event for notifications."""
    job_id: str
    repo_name: str
    branch: str
    status: str  # "success", "escalated", "failed"
    confidence: float
    explanation: str
    patch_diff: str = ""
    pr_url: str = ""
    source: str = "slm"
    fingerprint: str = ""
    timestamp: str = ""  # ISO format


class BaseNotifier(ABC):
    """Abstract base class for all notifiers."""

    @abstractmethod
    def send(self, event: NotificationEvent) -> bool:
        """Sends the notification. Returns True on success, False otherwise."""
        pass

    def format_message(self, event: NotificationEvent) -> str:
        """Provides a plain-text fallback message."""
        return (
            f"DCSP Notification: {event.status.upper()}\n"
            f"Repo: {event.repo_name} ({event.branch})\n"
            f"Confidence: {event.confidence:.2f}\n"
            f"Explanation: {event.explanation}"
        )
