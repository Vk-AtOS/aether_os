"""
Git repository manager for the AetherOS CI/CD phase.
Handles cloning and pulling repositories to provide source context.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
import urllib.parse
from pathlib import Path
from typing import Optional

from aether_os.core.security.git_remote import check_https_remote_pinned
from aether_os.core.security.safe_http import UnsafeURL


class RepoError(Exception):
    """Raised when repository operations fail."""
    pass


def _auth_env(host: str) -> dict[str, str]:
    """The platform token for `host` as a git config passed in the ENVIRONMENT (GIT_CONFIG_*), scoped to that
    host's URL prefix. It is never part of the clone URL, so it is not in the process list, not in git's error
    output and not written to .git/config."""
    creds = {"github.com": ("x-access-token", os.environ.get("GITHUB_TOKEN")),
             "gitlab.com": ("oauth2", os.environ.get("GITLAB_TOKEN"))}
    user, token = creds.get(host, ("", None))
    if not token:
        return {}
    basic = base64.b64encode(f"{user}:{token}".encode()).decode()
    return {"GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"http.https://{host}/.extraheader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}"}


class RepoManager:
    """Manages local cache of git repositories."""

    def __init__(self, cache_dir: Optional[str] = None) -> None:
        # private to the service user: the old default /tmp/aether_repos is world-writable ground
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".aether_os" / "repo_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def clone_or_pull(self, repo_url: str, commit_sha: Optional[str] = None) -> str:
        """
        Ensures the repository is present and up to date.
        Returns the local path to the repository.
        """
        # A user-supplied URL: the same checks as the intake router (https, no credentials, public addresses).
        try:
            remote = check_https_remote_pinned(repo_url)
            repo_url = remote.url
        except UnsafeURL as exc:
            raise RepoError(f"Repository URL refused: {exc}") from exc
        if commit_sha is not None and not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit_sha):
            raise RepoError("commit_sha must be a hex commit id")     # else it is a git option (--orphan ...)
        host = (urllib.parse.urlsplit(repo_url).hostname or "").lower()
        # only for the host the token belongs to (a substring test sent the GitHub token to
        # https://evil.example/github.com/x)
        auth = _auth_env(host)

        # Extract repo name from URL (e.g., https://github.com/org/repo.git -> repo)
        repo_name = re.sub(r"[^A-Za-z0-9._-]", "_", repo_url.rstrip("/").split("/")[-1].removesuffix(".git")).strip(".")
        if not repo_name:
            raise RepoError("Repository URL refused: no repository name")
        # the whole URL is in the key: org-a/app and org-b/app must not share one cache directory
        repo_path = self.cache_dir / f"{repo_name}-{hashlib.sha256(repo_url.encode()).hexdigest()[:12]}"

        try:
            if not repo_path.exists():
                # Clone
                self._run_git(["clone", "--", repo_url, str(repo_path)], pin=remote.git_args(), auth=auth)
            else:
                # Fetch and pull
                self._run_git(["fetch", "--all"], cwd=str(repo_path), pin=remote.git_args(), auth=auth)
                if commit_sha:
                    self._run_git(["checkout", commit_sha], cwd=str(repo_path))
                else:
                    self._run_git(["pull"], cwd=str(repo_path), pin=remote.git_args(), auth=auth)

            return str(repo_path)
        except subprocess.TimeoutExpired as e:
            raise RepoError("Git operation timed out") from e
        except subprocess.CalledProcessError as e:
            raise RepoError(f"Git operation failed: {e.stderr or str(e)}") from e

    def _run_git(self, args: list[str], cwd: Optional[str] = None, pin: Optional[list[str]] = None,
                 auth: Optional[dict[str, str]] = None) -> str:
        """Helper to run git commands."""
        # Only https may be spoken, whatever the URL (or a redirect) says; no prompts.
        env = os.environ.copy()
        env["GIT_ALLOW_PROTOCOL"] = "https"
        env["GIT_TERMINAL_PROMPT"] = "0"
        env.update(auth or {})

        result = subprocess.run(
            ["git", *(pin or []), *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            env=env,
            timeout=120,
        )
        return result.stdout
