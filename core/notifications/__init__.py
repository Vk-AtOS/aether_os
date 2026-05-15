"""AetherOS notification dispatchers (email, in-app)."""
from .email import EmailNotifier, get_email_notifier

__all__ = ["EmailNotifier", "get_email_notifier"]
