"""
Local git patch applier for the AetherOS CI/CD phase.
Applies generated patches to local repository clones and manages branches.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class PatchResult:
    """Result of a patch application operation."""
    success: bool
    applied_files: List[str] = field(default_factory=list)
    error: str = ""
    commit_sha: str = ""
    branch_name: str = ""


class PatchApplier:
    """Applies patches to a local git repository."""

    def __init__(self, repo_path: str) -> None:
        self.repo_path = Path(repo_path)

    def apply(self, patch_diff: str) -> PatchResult:
        """
        Writes patch_diff to a temp file and applies it using git apply.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as tf:
            tf.write(patch_diff)
            temp_path = tf.name

        try:
            # 1. Dry run check
            check_cmd = ["git", "apply", "--check", temp_path]
            subprocess.run(check_cmd, cwd=str(self.repo_path), capture_output=True, text=True, check=True)

            # 2. Real application
            apply_cmd = ["git", "apply", temp_path]
            subprocess.run(apply_cmd, cwd=str(self.repo_path), capture_output=True, text=True, check=True)

            # Extract affected files (heuristic: look at diff --git lines)
            applied_files = []
            for line in patch_diff.splitlines():
                if line.startswith("--- a/") or line.startswith("+++ b/"):
                    filename = line[6:].strip()
                    if filename not in applied_files:
                        applied_files.append(filename)

            return PatchResult(success=True, applied_files=applied_files)

        except subprocess.CalledProcessError as e:
            return PatchResult(success=False, error=e.stderr or str(e))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def create_branch(self, branch_name: str) -> str:
        """Creates and switches to a new git branch."""
        cmd = ["git", "checkout", "-b", branch_name]
        subprocess.run(cmd, cwd=str(self.repo_path), capture_output=True, text=True, check=True)
        return branch_name

    def commit_patch(self, message: str) -> str:
        """Adds all changes and commits them."""
        subprocess.run(["git", "add", "-A"], cwd=str(self.repo_path), check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=str(self.repo_path), check=True)
        
        sha_cmd = ["git", "rev-parse", "HEAD"]
        result = subprocess.run(sha_cmd, cwd=str(self.repo_path), capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def push_branch(self, branch_name: str, remote: str = "origin") -> bool:
        """Pushes the specified branch to the remote."""
        try:
            cmd = ["git", "push", remote, branch_name]
            subprocess.run(cmd, cwd=str(self.repo_path), capture_output=True, text=True, check=True)
            return True
        except subprocess.CalledProcessError:
            return False
