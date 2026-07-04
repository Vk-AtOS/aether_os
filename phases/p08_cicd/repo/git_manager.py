"""
Git repository manager for the AetherOS CI/CD phase.
Handles cloning and pulling repositories to provide source context.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional


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
        # Embed tokens if present in env
        github_token = os.environ.get("GITHUB_TOKEN")
        gitlab_token = os.environ.get("GITLAB_TOKEN")
        
        authenticated_url = repo_url
        if github_token and "github.com" in repo_url:
            authenticated_url = repo_url.replace("https://", f"https://x-access-token:{github_token}@")
        elif gitlab_token and "gitlab.com" in repo_url:
            authenticated_url = repo_url.replace("https://", f"https://oauth2:{gitlab_token}@")

        # Extract repo name from URL (e.g., https://github.com/org/repo.git -> repo)
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        repo_path = self.cache_dir / repo_name

        try:
            if not repo_path.exists():
                # Clone
                self._run_git(["clone", authenticated_url, str(repo_path)])
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
        except subprocess.CalledProcessError as e:
            raise RepoError(f"Git operation failed: {e.stderr or str(e)}")

    def get_local_path(self, repo_name: str) -> Optional[str]:
        """Returns the local path if the repo is cached."""
        repo_path = self.cache_dir / repo_name
        return str(repo_path) if repo_path.exists() else None

    def _run_git(self, args: list[str], cwd: Optional[str] = None) -> str:
        """Helper to run git commands."""
        env = os.environ.copy()
        # Add tokens to env if needed for auth (git uses these if configured)
        # Note: In a real scenario, we might embed tokens in the URL instead.
        
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            env=env
        )
        return result.stdout
