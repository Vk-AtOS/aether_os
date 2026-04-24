"""
CI adapter detection logic.
"""

from __future__ import annotations

from typing import Any, Optional
from aether_os.phases.p08_cicd.adapters.base import CIAdapter
from aether_os.phases.p08_cicd.adapters.github import GitHubActionsAdapter
from aether_os.phases.p08_cicd.adapters.jenkins import JenkinsAdapter
from aether_os.phases.p08_cicd.adapters.gitlab import GitLabCIAdapter


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
