"""
Standardized PR/MR creator for DCSP.
Handles API interactions with GitHub and GitLab to propose repair patches.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional


@dataclass
class PRResult:
    """Result of a PR/MR creation attempt."""
    success: bool
    url: str = ""
    number: int = 0
    error: str = ""


class PRCreator:
    """Creates Pull Requests (GitHub) or Merge Requests (GitLab)."""

    def __init__(self, repo_name: str, token: str = "") -> None:
        self.repo_name = repo_name # e.g. "acme/billing-service"
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.gitlab_token = os.environ.get("GITLAB_TOKEN", "")

    def create_github_pr(self, branch: str, title: str, body: str, base: str = "main") -> PRResult:
        """Creates a Pull Request on GitHub."""
        url = f"https://api.github.com/repos/{self.repo_name}/pulls"
        data = {
            "title": title,
            "head": branch,
            "base": base,
            "body": body
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json"
        }

        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers, method="POST")
            with urllib.request.urlopen(req) as resp:
                res_data = json.loads(resp.read().decode())
                return PRResult(success=True, url=res_data["html_url"], number=res_data["number"])
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            return PRResult(success=False, error=f"GitHub API Error ({e.code}): {error_body}")
        except Exception as e:
            return PRResult(success=False, error=str(e))

    def create_gitlab_mr(self, branch: str, title: str, body: str, base: str = "main") -> PRResult:
        """Creates a Merge Request on GitLab."""
        # URL encode repo name for GitLab
        encoded_repo = self.repo_name.replace("/", "%2F")
        url = f"https://gitlab.com/api/v4/projects/{encoded_repo}/merge_requests"
        data = {
            "title": title,
            "source_branch": branch,
            "target_branch": base,
            "description": body
        }
        headers = {
            "PRIVATE-TOKEN": self.gitlab_token,
            "Content-Type": "application/json"
        }

        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers, method="POST")
            with urllib.request.urlopen(req) as resp:
                res_data = json.loads(resp.read().decode())
                return PRResult(success=True, url=res_data["web_url"], number=res_data["iid"])
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            return PRResult(success=False, error=f"GitLab API Error ({e.code}): {error_body}")
        except Exception as e:
            return PRResult(success=False, error=str(e))
