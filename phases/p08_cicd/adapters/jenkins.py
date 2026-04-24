"""
Jenkins CI adapter.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse
from aether_os.phases.p08_cicd.adapters.base import CIAdapter, CIFailureEvent


class JenkinsAdapter(CIAdapter):
    """Adapter for Jenkins build webhooks."""

    @property
    def name(self) -> str:
        return "jenkins"

    def parse(self, payload: dict[str, Any]) -> Optional[CIFailureEvent]:
        """Detect and parse Jenkins payloads."""
        if "build" not in payload:
            return None

        try:
            build = payload["build"]
            full_url = build["full_url"]
            # Extract repo name from full_url (e.g., http://jenkins/job/my-repo/1/ -> my-repo)
            parsed_url = urlparse(full_url)
            # Jenkins paths are often /job/name/build_number/
            path_parts = [p for p in parsed_url.path.strip("/").split("/") if p != "job"]
            repo_name = path_parts[0] if path_parts else "unknown"

            params = build.get("parameters", {})
            branch = params.get("BRANCH", "unknown")
            
            scm = build.get("scm", {})
            commit_sha = scm.get("commit", "unknown")
            log_output = build.get("log", "")

            return CIFailureEvent(
                repo_name=repo_name,
                branch=branch,
                commit_sha=commit_sha,
                log_output=log_output,
                ci_system=self.name,
                raw_payload=payload
            )
        except (KeyError, TypeError, IndexError):
            return None
