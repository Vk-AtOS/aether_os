"""
GitLab CI adapter.
"""

from __future__ import annotations

from typing import Any, Optional
from aether_os.phases.p08_cicd.adapters.base import CIAdapter, CIFailureEvent


class GitLabCIAdapter(CIAdapter):
    """Adapter for GitLab CI pipeline webhooks."""

    @property
    def name(self) -> str:
        return "gitlab_ci"

    def parse(self, payload: dict[str, Any]) -> Optional[CIFailureEvent]:
        """Detect and parse GitLab CI payloads."""
        if payload.get("object_kind") != "pipeline":
            return None

        try:
            project = payload["project"]
            obj_attr = payload["object_attributes"]
            
            repo_name = project["path_with_namespace"]
            branch = obj_attr["ref"]
            commit_sha = obj_attr["sha"]
            log_output = payload.get("log_output", "")

            return CIFailureEvent(
                repo_name=repo_name,
                branch=branch,
                commit_sha=commit_sha,
                log_output=log_output,
                ci_system=self.name,
                raw_payload=payload
            )
        except (KeyError, TypeError):
            return None
