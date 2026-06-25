"""
Tests for RepoManager.
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path
from src.repo.git_manager import RepoManager, RepoError


def test_get_local_path_missing(tmp_path):
    """Test that missing repo returns None."""
    manager = RepoManager(str(tmp_path))
    assert manager.get_local_path("nonexistent") is None


def test_cache_dir_created(tmp_path):
    """Test that cache directory is created on init."""
    cache_dir = tmp_path / "new_cache"
    assert not cache_dir.exists()
    RepoManager(str(cache_dir))
    assert cache_dir.exists()


def test_repo_error_on_bad_url(tmp_path):
    """Test that bad URLs raise RepoError."""
    manager = RepoManager(str(tmp_path))
    # Passing an obviously invalid URL that git will fail on
    with pytest.raises(RepoError):
        manager.clone_or_pull("https://invalid.example.com/repo.git")
