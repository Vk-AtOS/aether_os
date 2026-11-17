"""
Git repository manager for the AetherOS CI/CD phase.
Handles cloning and pulling repositories to provide source context.
"""

from __future__ import annotations

import os
import re
import subprocess
import urllib.parse
from pathlib import Path
from typing import Optional

from aether_os.core.security.git_remote import check_https_remote
from aether_os.core.security.safe_http import UnsafeURL


class RepoError(Exception):
    """Raised when repository operations fail."""
    pass


class RepoManager:
    """Manages local cache of git repositories."""

    def __init__(self, cache_dir: str = "/tmp/aether_repos") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def clone_or_pull(self, repo_url: str, commit_sha: Optional[str] = None) -> str:
        """
        Ensures the repository is present and up to date.
        Returns the local path to the repository.
        """
        # A user-supplied URL: the same checks as the intake router (https, no credentials, public addresses).
        try:
            repo_url = check_https_remote(repo_url)
        except UnsafeURL as exc:
            raise RepoError(f"Repository URL refused: {exc}") from exc
        if commit_sha is not None and not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit_sha):
            raise RepoError("commit_sha must be a hex commit id")     # else it is a git option (--orphan ...)
        host = (urllib.parse.urlsplit(repo_url).hostname or "").lower()

        # Embed tokens if present in env, and only for the host they belong to (a substring test sent the
        # GitHub token to https://evil.example/github.com/x).
        github_token = os.environ.get("GITHUB_TOKEN")
        gitlab_token = os.environ.get("GITLAB_TOKEN")
        
        authenticated_url = repo_url
        if github_token and host == "github.com":
            authenticated_url = repo_url.replace("https://", f"https://x-access-token:{github_token}@")
        elif gitlab_token and host == "gitlab.com":
            authenticated_url = repo_url.replace("https://", f"https://oauth2:{gitlab_token}@")

        # Extract repo name from URL (e.g., https://github.com/org/repo.git -> repo)
        repo_name = re.sub(r"[^A-Za-z0-9._-]", "_", repo_url.rstrip("/").split("/")[-1].removesuffix(".git")).strip(".")
        if not repo_name:
            raise RepoError("Repository URL refused: no repository name")
        repo_path = self.cache_dir / repo_name

        try:
            if not repo_path.exists():
                # Clone
                self._run_git(["clone", "--", authenticated_url, str(repo_path)])
            else:
                # Fetch and pull
                self._run_git(["fetch", "--all"], cwd=str(repo_path))
                if commit_sha:
                    self._run_git(["checkout", commit_sha], cwd=str(repo_path))
                else:
                    # Use authenticated URL for pull as well
                    self._run_git(["remote", "set-url", "origin", authenticated_url], cwd=str(repo_path))
                    self._run_git(["pull"], cwd=str(repo_path))

            return str(repo_path)
        except subprocess.TimeoutExpired as e:
            raise RepoError("Git operation timed out") from e
        except subprocess.CalledProcessError as e:
            raise RepoError(f"Git operation failed: {e.stderr or str(e)}") from e

    def get_local_path(self, repo_name: str) -> Optional[str]:
        """Returns the local path if the repo is cached."""
        repo_path = self.cache_dir / repo_name
        return str(repo_path) if repo_path.exists() else None

    def _run_git(self, args: list[str], cwd: Optional[str] = None) -> str:
        """Helper to run git commands."""
        # Only https may be spoken, whatever the URL (or a redirect) says; no prompts.
        env = os.environ.copy()
        env["GIT_ALLOW_PROTOCOL"] = "https"
        env["GIT_TERMINAL_PROMPT"] = "0"

        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            env=env,
            timeout=120,
        )
        return result.stdout
