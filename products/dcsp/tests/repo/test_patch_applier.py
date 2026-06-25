"""
Tests for local patch applier.
"""

from __future__ import annotations

import os
import subprocess
import pytest
from pathlib import Path
from src.repo.patch_applier import PatchApplier, PatchResult


@pytest.fixture
def temp_git_repo(tmp_path):
    """Initializes a real temporary git repository."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    
    # Init git
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_dir), check=True)
    
    # Create initial commit
    file_path = repo_dir / "app.py"
    file_path.write_text("def hello():\n    print('hello')\n")
    
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo_dir), check=True)
    
    return repo_dir


def test_apply_valid_patch(temp_git_repo):
    """Test applying a valid unified diff patch."""
    # Note: git apply is very sensitive to whitespace and line counts
    diff = (
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def hello():\n"
        "-    print('hello')\n"
        "+    print('hi')\n"
    )
    
    applier = PatchApplier(str(temp_git_repo))
    result = applier.apply(diff)
    
    assert result.success is True
    assert "app.py" in result.applied_files
    
    # Verify content changed
    content = (temp_git_repo / "app.py").read_text()
    assert "print('hi')" in content


def test_apply_invalid_patch(temp_git_repo):
    """Test applying a malformed patch."""
    applier = PatchApplier(str(temp_git_repo))
    result = applier.apply("this is not a diff")
    
    assert result.success is False
    assert result.error != ""


def test_create_branch(temp_git_repo):
    """Test creating a new branch."""
    applier = PatchApplier(str(temp_git_repo))
    branch_name = "test/fix-branch"
    
    created = applier.create_branch(branch_name)
    assert created == branch_name
    
    # Verify we are on that branch
    res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(temp_git_repo), capture_output=True, text=True)
    assert res.stdout.strip() == branch_name


def test_patch_result_fields():
    """Verify PatchResult dataclass structure."""
    res = PatchResult(success=True, applied_files=["f1.py"], error="no error", commit_sha="abc", branch_name="fix")
    assert res.success is True
    assert res.applied_files == ["f1.py"]
    assert res.error == "no error"
    assert res.commit_sha == "abc"
    assert res.branch_name == "fix"
