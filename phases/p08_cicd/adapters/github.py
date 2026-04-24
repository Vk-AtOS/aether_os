"""
GitHub Actions CI adapter.
"""

from __future__ import annotations

from typing import Any, Optional
from aether_os.phases.p08_cicd.adapters.base import CIAdapter, CIFailureEvent


class GitHubActionsAdapter(CIAdapter):
    """Adapter for GitHub Actions webhooks."""

    @property
    def name(self) -> str:
        return "github_actions"

    def parse(self, payload: dict[str, Any]) -> Optional[CIFailureEvent]:
        """
        Detect and parse GitHub Actions payloads.
        Supports both workflow_run and check_run events.
        """
        try:
            repo_name = payload["repository"]["full_name"]
            log_output = payload.get("log_output", "")

            if "workflow_run" in payload:
                wf = payload["workflow_run"]
                branch = wf["head_branch"]
                commit_sha = wf["head_sha"]
            elif "check_run" in payload:
                cr = payload["check_run"]
                branch = cr["check_suite"]["head_branch"]
                commit_sha = cr["head_sha"]
            else:
                return None

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
