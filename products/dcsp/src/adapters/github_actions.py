"""
GitHub Actions CI adapter.
"""

from __future__ import annotations

from typing import Any, Optional
from src.adapters.base import CIAdapter, CIFailureEvent


class GitHubActionsAdapter(CIAdapter):
    """Adapter for GitHub Actions webhooks."""

    @property
    def name(self) -> str:
        return "github_actions"

    def parse(self, payload: dict[str, Any]) -> Optional[CIFailureEvent]:
        """
        Detect and parse GitHub Actions payloads.
        Supports both workflow_run and check_run events.

        All optional fields use .get() so the documented minimal payload
        {"repository": "owner/repo", "workflow_run": {"conclusion": "failure",
        "logs_url": "..."}} is accepted without KeyError.
        """
        try:
            repo_obj = payload.get("repository") or {}
            # Accept both {"repository": {"full_name": "..."}} and
            # {"repository": "owner/repo"} (string shorthand from docs)
            if isinstance(repo_obj, str):
                repo_name = repo_obj
            else:
                repo_name = repo_obj.get("full_name") or repo_obj.get("name") or "unknown"

            log_output = payload.get("log_output", "")

            if "workflow_run" in payload:
                wf = payload["workflow_run"] or {}
                # head_branch / head_sha are optional in the documented payload
                branch = (
                    wf.get("head_branch")
                    or wf.get("head_commit", {}).get("branch")
                    or "unknown"
                )
                commit_sha = (
                    wf.get("head_sha")
                    or wf.get("head_commit", {}).get("id")
                    or ""
                )
            elif "check_run" in payload:
                cr = payload["check_run"] or {}
                check_suite = cr.get("check_suite") or {}
                branch = check_suite.get("head_branch") or "unknown"
                commit_sha = cr.get("head_sha") or ""
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
        except (KeyError, TypeError, AttributeError):
            return None
