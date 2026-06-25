"""
CI adapter detection logic.
"""

from __future__ import annotations

from typing import Any, Optional
from src.adapters.base import CIAdapter
from src.adapters.github_actions import GitHubActionsAdapter
from src.adapters.jenkins import JenkinsAdapter
from src.adapters.gitlab_ci import GitLabCIAdapter


def detect_adapter(payload: dict[str, Any]) -> Optional[CIAdapter]:
    """
    Tries each available CI adapter in order and returns the first one that matches the payload.
    """
    adapters = [
        GitHubActionsAdapter(),
        JenkinsAdapter(),
        GitLabCIAdapter(),
    ]

    for adapter in adapters:
        if adapter.parse(payload) is not None:
            return adapter

    return None
