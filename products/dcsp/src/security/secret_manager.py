"""
Secret manager for CI webhook verification.
"""

from __future__ import annotations

import os


class SecretManager:
    """Manages retrieval of CI webhook secrets."""

    def get_webhook_secret(self, ci_system: str) -> str:
        """
        Returns the configured secret for a given CI system.
        """
        if ci_system == "github_actions":
            return os.environ.get("GITHUB_WEBHOOK_SECRET", "")
        elif ci_system == "gitlab_ci":
            return os.environ.get("GITLAB_WEBHOOK_SECRET", "")
        elif ci_system == "jenkins":
            return os.environ.get("JENKINS_WEBHOOK_TOKEN", "")
        return ""


# Global singleton
GLOBAL_SECRET_MANAGER = SecretManager()
