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
import stat
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


_CHUNK = 1024 * 1024
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _walk(root_fd: int, parts: List[str], create: bool) -> int:
    """fd of root/parts, each step opened O_NOFOLLOW relative to the previous fd, so a
    planted symlink in any directory is an OSError, never followed. Caller closes it."""
    fd = os.dup(root_fd)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o755, dir_fd=fd)
                except FileExistsError as e:
                    logger.debug("directory already exists, reusing %s: %s", part, e)
            nxt = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _copy_one(src_fd: int, dst_fd: int, name: str, budget: int) -> int:
    """Copy one regular file between directory fds; bytes copied, or -1 if it is not a
    regular file / is a link (skipped). Raises ProjectTooLarge past `budget` bytes."""
    try:   # O_NONBLOCK: opening a FIFO must not hang; fstat then rejects it
        rfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=src_fd)
    except OSError:
        return -1
    with os.fdopen(rfd, "rb") as src:
        if not stat.S_ISREG(os.fstat(src.fileno()).st_mode):
            return -1
        wfd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                      0o644, dir_fd=dst_fd)
        copied = 0
        with os.fdopen(wfd, "wb") as out:
            while chunk := src.read(_CHUNK):
                copied += len(chunk)
                if copied > budget:   # counted as written, not as planned: the file may have grown
                    raise ProjectTooLarge("the project grew past the copy limit while copying")
                out.write(chunk)
    return copied


def copy_project(src: Path, dst: Path, plan: List[Tuple[str, int]]) -> int:
    """Copy the planned files; returns how many were copied. Every source and destination
    component is opened without following links at copy time (the plan is only a list of
    names), non-regular files and links are skipped, bytes are counted as copied, and a
    failed or oversized copy removes the destination folder."""
    max_bytes, _ = limits()
    created = not dst.exists()
    dst.mkdir(parents=True, exist_ok=True)
    copied = skipped = total = 0
    try:
        src_root = os.open(src, _DIR_FLAGS)   # the root itself must not be a link
        try:
            dst_root = os.open(dst, _DIR_FLAGS)
            try:
                for rel, _size in plan:
                    *dirs, name = Path(rel).parts
                    try:
                        sfd = _walk(src_root, dirs, create=False)
                    except OSError:
                        skipped += 1
                        continue
                    try:
                        dfd = _walk(dst_root, dirs, create=True)
                        try:
                            n = _copy_one(sfd, dfd, name, max_bytes - total)
                        finally:
                            os.close(dfd)
                    finally:
                        os.close(sfd)
                    if n < 0:
                        skipped += 1
                    else:
                        total, copied = total + n, copied + 1
            finally:
                os.close(dst_root)
        finally:
            os.close(src_root)
    except BaseException:
        if created:
            shutil.rmtree(dst, ignore_errors=True)
        raise
    if skipped:
        logger.warning("project_copy: skipped %d links or non-regular files in %s", skipped, src)
    logger.info("project_copy: %d files from %s to %s", copied, src, dst)
    return copied
