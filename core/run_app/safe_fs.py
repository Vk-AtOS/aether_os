"""Host-side file access inside a run directory the sandbox can write to.

A sandboxed process can plant a symlink in its run dir (a log, a tsconfig, a stub). A
plain open()/write_text() by the gateway would follow it and write or read anywhere the
gateway can. Every gateway read or write of a path the sandbox could have touched goes
through here: the parent must resolve inside the run dir and the final component is opened
with O_NOFOLLOW, so a planted link is an error, never a write elsewhere.

Platform-owned files (launch state, the platform log) do not live in the run dir at all:
see preview_state.state_dir().
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Union

from aether_os.core.errors import SandboxViolation

PathLike = Union[str, Path]


def _checked(root: PathLike, path: PathLike) -> Path:
    root_r, p = Path(root).resolve(), Path(path)
    parent = p.parent.resolve()
    if not parent.is_relative_to(root_r):
        raise SandboxViolation(f"{p} resolves outside the run dir {root_r}")
    return parent / p.name


def _open(root: PathLike, path: PathLike, flags: int) -> int:
    target = _checked(root, path)
    try:
        return os.open(target, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
    except OSError as exc:  # ELOOP: the final component is a symlink
        raise SandboxViolation(f"refusing to open {target}: {exc.strerror}") from exc


def safe_write_text(root: PathLike, path: PathLike, text: str) -> None:
    with os.fdopen(_open(root, path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC), "w", encoding="utf-8") as fh:
        fh.write(text)


def safe_read_text(root: PathLike, path: PathLike) -> str:
    with os.fdopen(_open(root, path, os.O_RDONLY), "r", encoding="utf-8") as fh:
        return fh.read()


def open_log_fd(path: PathLike) -> int:
    """Append-mode fd for a log the sandboxed app writes to (never follows a symlink)."""
    try:
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
    except OSError as exc:
        raise SandboxViolation(f"refusing to open log {path}: {exc.strerror}") from exc
