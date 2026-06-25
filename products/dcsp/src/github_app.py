"""GitHub App integration for DCSP autonomous fix PRs."""
from __future__ import annotations

import hmac
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from github import GithubIntegration, Github, GithubException

logger = logging.getLogger(__name__)

GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID", "")
GITHUB_APP_PRIVATE_KEY_PATH = os.environ.get(
    "GITHUB_APP_PRIVATE_KEY_PATH", "dcsp-github-app.pem"
)
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")


def _load_private_key() -> Optional[str]:
    """Load the GitHub App private key from file or environment variable."""
    path = Path(GITHUB_APP_PRIVATE_KEY_PATH)
    if path.exists():
        return path.read_text()
    env_key = os.environ.get("GITHUB_APP_PRIVATE_KEY", "")
    if env_key:
        return env_key.replace("\\n", "\n")
    return None


def get_installation_client(installation_id: int) -> Optional[Github]:
    """Return an authenticated Github client for a specific installation."""
    private_key = _load_private_key()
    if not private_key or not GITHUB_APP_ID:
        logger.warning(
            "GitHub App not configured — GITHUB_APP_ID or private key missing"
        )
        return None
    try:
        integration = GithubIntegration(int(GITHUB_APP_ID), private_key)
        token = integration.get_access_token(installation_id).token
        return Github(token)
    except Exception as e:
        logger.error("Failed to get GitHub installation client: %s", e)
        return None


def create_fix_pr(
    installation_id: int,
    repo_full_name: str,
    base_branch: str,
    fix_branch: str,
    file_path: str,
    original_content: str,
    fixed_content: str,
    commit_message: str,
    pr_title: str,
    pr_body: str,
) -> Optional[str]:
    """
    Create a branch, commit the fix, and open a PR.
    Returns the PR URL or None on failure.
    original_content is accepted for API symmetry but the live file SHA is
    fetched from the repo to avoid stale-SHA conflicts.
    """
    client = get_installation_client(installation_id)
    if not client:
        return None
    try:
        repo = client.get_repo(repo_full_name)
        base_sha = repo.get_branch(base_branch).commit.sha
        # Create fix branch
        repo.create_git_ref(f"refs/heads/{fix_branch}", sha=base_sha)
        # Get current file SHA (do not rely on caller's copy)
        file_obj = repo.get_contents(file_path, ref=base_branch)
        # Commit the fix
        repo.update_file(
            path=file_path,
            message=commit_message,
            content=fixed_content,
            sha=file_obj.sha,
            branch=fix_branch,
        )
        # Open PR
        pr = repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=fix_branch,
            base=base_branch,
        )
        logger.info("Created fix PR: %s", pr.html_url)
        return pr.html_url
    except GithubException as e:
        logger.error("GitHub API error creating fix PR: %s", e)
        return None
    except Exception as e:
        logger.error("Unexpected error creating fix PR: %s", e)
        return None


def get_repo_file(
    installation_id: int,
    repo_full_name: str,
    file_path: str,
    ref: str = "main",
) -> Optional[str]:
    """Fetch a file's decoded content from the repo."""
    client = get_installation_client(installation_id)
    if not client:
        return None
    try:
        repo = client.get_repo(repo_full_name)
        contents = repo.get_contents(file_path, ref=ref)
        return contents.decoded_content.decode("utf-8")
    except Exception as e:
        logger.error("Failed to fetch repo file %s: %s", file_path, e)
        return None


def list_python_files(
    installation_id: int,
    repo_full_name: str,
    ref: str = "main",
) -> list[str]:
    """Return all .py file paths in the repo."""
    client = get_installation_client(installation_id)
    if not client:
        return []
    try:
        repo = client.get_repo(repo_full_name)
        tree = repo.get_git_tree(ref, recursive=True)
        return [
            item.path
            for item in tree.tree
            if item.path.endswith(".py") and item.type == "blob"
        ]
    except Exception as e:
        logger.error("Failed to list repo files: %s", e)
        return []


def get_existing_dcsp_pr(
    installation_id: int, repo_full_name: str, fix_branch: str
) -> Optional[str]:
    """Return URL of an existing open DCSP PR for this fix branch, or None."""
    client = get_installation_client(installation_id)
    if not client:
        return None
    try:
        repo = client.get_repo(repo_full_name)
        pulls = repo.get_pulls(state="open", head=f"{repo.owner.login}:{fix_branch}")
        for pr in pulls:
            return pr.html_url  # already exists
    except Exception as e:
        logger.warning("Could not check existing PRs: %s", e)
    return None


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub App webhook HMAC-SHA256 signature."""
    if not GITHUB_WEBHOOK_SECRET:
        logger.warning(
            "GITHUB_WEBHOOK_SECRET not set — skipping signature verification"
        )
        return True
    if not signature:
        return False
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
