"""The one gate for the run directory every quality/compliance reader is rooted at.

Generated projects are written by sandboxed code, which can plant symlinks. Readers open every
path with safe_fs relative to a root; the root itself must therefore be a real, absolute
directory that the caller names explicitly. There is no default: a reader that is not told its
root is a bug, not a reason to guess one (the file's own parent would let a link above it escape).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from aether_os.core.errors import SandboxViolation


def require_project_root(root: Optional[Union[str, Path]]) -> Path:
    """The run directory as a Path, or SandboxViolation (missing, relative, a link, not a dir)."""
    if root is None or str(root) == "":
        raise SandboxViolation("no run directory given: refusing to read without a root")
    p = Path(root)
    if not p.is_absolute():
        raise SandboxViolation(f"run directory {p} is not absolute")
    if p.is_symlink():
        raise SandboxViolation(f"run directory {p} is a symlink")
    if not p.is_dir():
        raise SandboxViolation(f"run directory {p} is not a directory")
    return p


def relative_to_root(root: Path, path: Union[str, Path]) -> Path:
    """path relative to root; a path outside root is refused."""
    try:
        return Path(path).relative_to(root)
    except ValueError:
        raise SandboxViolation(f"{path} is outside the run dir {root}") from None
