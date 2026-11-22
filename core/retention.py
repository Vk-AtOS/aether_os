"""Retention of the run artifact files (KAN-187). Used by the admin route and by scripts/retention_purge.py.

Symlinks are skipped (is_file()/stat() follow them, so age and size would be those of a file outside the
directory); empty directories are removed afterwards.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


def prune_artifact_files(root: Path, ttl_days: int, dry_run: bool = False, now: float | None = None) -> Tuple[List[str], int]:
    """Delete files under `root` last modified more than ttl_days ago. Returns (relative paths, bytes)."""
    if ttl_days < 1:
        raise ValueError("ttl_days must be at least 1")   # 0 or less moves the cutoff to now: every file would go
    cutoff = (now if now is not None else time.time()) - ttl_days * 86400
    files: List[str] = []
    size = 0
    if not root.exists():
        return files, size
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink() and p.stat().st_mtime < cutoff:
            size += p.stat().st_size
            files.append(str(p.relative_to(root)))
            if not dry_run:
                p.unlink(missing_ok=True)
    if not dry_run:
        for p in sorted(root.rglob("*"), reverse=True):
            if p.is_dir() and not p.is_symlink():
                try:
                    p.rmdir()
                except OSError as e:
                    logger.debug("keeping non-empty directory %s: %s", p, e)
    return files, size
