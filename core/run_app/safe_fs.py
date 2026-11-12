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

import logging
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Optional, Tuple, Union

from aether_os.core.errors import SandboxViolation

logger = logging.getLogger(__name__)
PathLike = Union[str, Path]
MAX_READ_BYTES = 2 * 1024 * 1024
MAX_WALK_FILES = 20000
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


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


def safe_write_bytes(root: PathLike, path: PathLike, data: bytes) -> None:
    with os.fdopen(_open(root, path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC), "wb") as fh:
        fh.write(data)


def safe_makedirs(root: PathLike, path: PathLike) -> None:
    """mkdir -p for root/path, each level created and entered with O_NOFOLLOW relative to
    the previous fd: a planted link on the way is a SandboxViolation, never followed."""
    parts = _parts(root, path)
    if parts is None:
        raise SandboxViolation(f"{path} is outside the run dir {root}")
    fd = os.open(root, _DIR_FLAGS)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o755, dir_fd=fd)
            except FileExistsError:
                pass
            nxt = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
    except OSError as exc:
        raise SandboxViolation(f"refusing to create {path}: {exc.strerror}") from exc
    finally:
        os.close(fd)


def safe_append_text(root: PathLike, path: PathLike, text: str) -> None:
    with os.fdopen(_open(root, path, os.O_WRONLY | os.O_CREAT | os.O_APPEND), "a", encoding="utf-8") as fh:
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


# ── read-only access for the gateway: nothing here ever follows a link ─────────────────
# Every component below `root` is opened relative to the previous directory fd with
# O_NOFOLLOW, so a symlinked folder, file or parent (planted by the sandboxed app, or swapped
# in between a listing and a read) is skipped, never read. Failures return None / [] (fail
# closed: the item is simply not shown). `path` may be absolute under root or relative to it.

def _parts(root: PathLike, path: PathLike) -> Optional[Tuple[str, ...]]:
    p, r = Path(path), Path(root)
    if p.is_absolute():
        for base in (r, r.resolve()):
            try:
                p = p.relative_to(base)
                break
            except ValueError:
                continue
        else:
            return None
    if p.as_posix() == ".":
        return ()
    parts = PurePosixPath(p.as_posix()).parts
    return None if ".." in parts or "." in parts else parts


def _walk_dir(root: PathLike, parts: Iterable[str]) -> int:
    fd = os.open(root, _DIR_FLAGS)
    try:
        for part in parts:
            nxt = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_regular(root: PathLike, path: PathLike):
    """Binary file object for a regular file at root/path, or None (missing, any link on the
    path, not a regular file, outside root). Never follows a link; never blocks on a FIFO."""
    parts = _parts(root, path)
    if not parts:
        return None
    try:
        dfd = _walk_dir(root, parts[:-1])
    except OSError:
        return None
    try:
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dfd)
    except OSError:
        return None
    finally:
        os.close(dfd)
    fh = os.fdopen(fd, "rb")
    if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
        fh.close()
        return None
    return fh


def stat_or_none(root: PathLike, path: PathLike) -> Optional[os.stat_result]:
    """fstat of a regular file reached without following any link, else None."""
    fh = _open_regular(root, path)
    if fh is None:
        return None
    with fh:
        return os.fstat(fh.fileno())


def file_size_or_none(root: PathLike, path: PathLike) -> Optional[int]:
    st = stat_or_none(root, path)
    return None if st is None else st.st_size


def read_prefix_or_none(root: PathLike, path: PathLike, n: int) -> Optional[Tuple[bytes, int]]:
    """(first n bytes, total size) of a regular file, or None."""
    fh = _open_regular(root, path)
    if fh is None:
        return None
    with fh:
        return fh.read(n), os.fstat(fh.fileno()).st_size


def read_bytes_or_none(root: PathLike, path: PathLike, max_bytes: int = MAX_READ_BYTES) -> Optional[bytes]:
    """The file's bytes, or None if missing, a link, not a regular file, outside root or
    larger than max_bytes (counted while reading, so a growing file cannot slip past)."""
    fh = _open_regular(root, path)
    if fh is None:
        return None
    with fh:
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        logger.warning("safe_fs: %s is larger than %d bytes, not read", path, max_bytes)
        return None
    return data


def read_text_or_none(root: PathLike, path: PathLike, max_bytes: int = MAX_READ_BYTES) -> Optional[str]:
    data = read_bytes_or_none(root, path, max_bytes)
    return None if data is None else data.decode("utf-8", errors="replace")


def list_dir(root: PathLike, path: PathLike = "") -> List[Tuple[str, bool]]:
    """(name, is_dir) of the real files and folders directly in root/path; links are left
    out. [] when the folder is missing, a link, or outside root."""
    parts = _parts(root, path) if str(path) else ()
    if parts is None:
        return []
    try:
        fd = _walk_dir(root, parts)
    except OSError:
        return []
    try:
        with os.scandir(fd) as it:
            return sorted((e.name, e.is_dir(follow_symlinks=False)) for e in it
                          if not e.is_symlink() and (e.is_dir(follow_symlinks=False)
                                                     or e.is_file(follow_symlinks=False)))
    except OSError:
        return []
    finally:
        os.close(fd)


def is_real_dir(root: PathLike, path: PathLike) -> bool:
    parts = _parts(root, path)
    if parts is None:
        return False
    try:
        os.close(_walk_dir(root, parts))
        return True
    except OSError:
        return False


def walk_files(root: PathLike, path: PathLike = "", skip_dirs: Iterable[str] = (),
               limit: int = MAX_WALK_FILES, skip_prefixes: Tuple[str, ...] = ()) -> List[Path]:
    """Paths (relative to root) of every real file under root/path, never entering or
    listing a link. At most `limit` entries."""
    skip = set(skip_dirs)
    out: List[Path] = []
    stack = [Path(*(_parts(root, path) or ()))] if str(path) else [Path()]
    while stack and len(out) < limit:
        rel = stack.pop()
        for name, is_dir in list_dir(root, rel):
            if is_dir:
                if name not in skip and not name.startswith(skip_prefixes):
                    stack.append(rel / name)
            else:
                out.append(rel / name)
                if len(out) >= limit:
                    break
    return sorted(out)
