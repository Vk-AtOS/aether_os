"""Copy a run's project folder into a new run (rerun / branch start from the parent's edited files).

What is NOT copied, because it is a secret, machine state or rebuilt anyway:
  * secrets: .env*, key and certificate files, credential files, .npmrc/.pypirc/.netrc, .ssh/.aws;
  * dependency and build output: node_modules, virtualenvs, __pycache__, dist, build, .git;
  * the run-app's own state: its log, preview stub/ui/db/credentials, sandbox HOME and TMPDIR;
  * symlinks of any kind (a sandboxed app can plant them): never followed, never copied.

The copy is size-limited (AETHER_FORK_COPY_MAX_MB, default 200; AETHER_FORK_COPY_MAX_FILES,
default 20000) and is planned completely before the first byte is written, so a folder that is
too big is refused without leaving a partial copy.
"""
from __future__ import annotations

import fnmatch
import logging
import os
import shutil
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

EXCLUDED_DIRS = {
    "node_modules", "__pycache__", "dist", "build", ".git", ".ssh", ".aws", "venv", ".venv",
    "_preview_stub", "_preview_ui", ".sandbox_home", ".sandbox_tmp", ".pytest_cache", ".mypy_cache",
}
EXCLUDED_DIR_PATTERNS = (".venv-*", "venv-*")
EXCLUDED_FILE_PATTERNS = (
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx", "*.crt", "id_rsa*", "id_ed25519*",
    "credentials*.json", "*credentials*.json", "secrets*", ".npmrc", ".pypirc", ".netrc",
    "run_app.log", "run_app_state.json", "_preview_requirements.txt", "preview.db",
    "preview_credentials.json", "*.sqlite", "*.sqlite3", "*.db", "*.pyc",
)


class ProjectTooLarge(ValueError):
    """The parent's folder exceeds the copy limits."""


def limits() -> Tuple[int, int]:
    return (int(float(os.environ.get("AETHER_FORK_COPY_MAX_MB", "200")) * 1024 * 1024),
            int(os.environ.get("AETHER_FORK_COPY_MAX_FILES", "20000")))


def _skip_dir(name: str) -> bool:
    return name in EXCLUDED_DIRS or any(fnmatch.fnmatch(name, p) for p in EXCLUDED_DIR_PATTERNS)


def _skip_file(name: str) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, p) for p in EXCLUDED_FILE_PATTERNS)


def plan_copy(src: Path) -> List[Tuple[str, int]]:
    """(relative path, size) of every file that would be copied; raises ProjectTooLarge."""
    max_bytes, max_files = limits()
    plan: List[Tuple[str, int]] = []
    total = 0
    if not src.is_dir() or src.is_symlink():
        return plan
    for root, dirs, files in os.walk(src, followlinks=False):
        dirs[:] = [d for d in dirs if not _skip_dir(d) and not (Path(root) / d).is_symlink()]
        for name in files:
            path = Path(root) / name
            if _skip_file(name) or path.is_symlink() or not path.is_file():
                continue
            size = path.stat().st_size
            total += size
            plan.append((str(path.relative_to(src)), size))
            if total > max_bytes or len(plan) > max_files:
                raise ProjectTooLarge(
                    f"the project is larger than the copy limit ({max_bytes // (1024 * 1024)} MB / {max_files} files)")
    return plan


def copy_project(src: Path, dst: Path, plan: List[Tuple[str, int]]) -> int:
    """Copy the planned files; returns how many were copied."""
    dst.mkdir(parents=True, exist_ok=True)
    for rel, _size in plan:
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / rel, target)
    logger.info("project_copy: %d files from %s to %s", len(plan), src, dst)
    return len(plan)
