"""
Repository and Indexing layer for DCSP.
"""

from __future__ import annotations

from src.repo.git_manager import RepoManager, RepoError
from src.repo.indexer import UniversalIndexer, GLOBAL_INDEXER
from src.repo.patch_applier import PatchApplier, PatchResult
from src.repo.pr_creator import PRCreator, PRResult

# Global repo manager instance
REPO_MANAGER = RepoManager()

__all__ = [
    "RepoManager", 
    "RepoError", 
    "UniversalIndexer", 
    "GLOBAL_INDEXER",
    "PatchApplier",
    "PatchResult",
    "PRCreator",
    "PRResult",
    "REPO_MANAGER"
]
