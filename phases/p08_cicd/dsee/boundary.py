"""
Patch boundary enforcement for DSEE.

Enforces hard limits on patch diffs: line count, single-file, and
excluded paths (manifests, CI, infra).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_LINES_CHANGED = 40

_FORBIDDEN_MANIFESTS = frozenset([
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Pipfile",
])

_FORBIDDEN_CI = frozenset([
    ".gitlab-ci.yml",
    "Jenkinsfile",
])

_FORBIDDEN_CI_PREFIXES = frozenset([
    ".github/",
    ".circleci/",
])

_FORBIDDEN_INFRA = frozenset([
    ".env",
    "Dockerfile",
    "docker-compose.yml",
])


def _normalize_path(path: str) -> str:
    """Strip a/ or b/ prefix from diff paths."""
    for prefix in ("a/", "b/"):
        if path.startswith(prefix):
            return path[len(prefix):].strip()
    return path.strip()


def _is_forbidden(path: str) -> bool:
    """Check if path is in any forbidden category."""
    norm = path.replace("\\", "/")
    name = norm.split("/")[-1] if "/" in norm else norm

    if name in _FORBIDDEN_MANIFESTS:
        return True
    if name in _FORBIDDEN_CI or norm == name and name in _FORBIDDEN_CI:
        return True
    for prefix in _FORBIDDEN_CI_PREFIXES:
        if norm.startswith(prefix) or "/" + prefix in norm:
            return True
    if name in _FORBIDDEN_INFRA:
        return True
    return False


def _parse_diff(diff: str) -> list[tuple[str, int, int]]:
    """
    Parse unified diff. Returns list of (filepath, additions, deletions).
    """
    if not diff or not diff.strip():
        return []

    files: list[tuple[str, int, int]] = []
    current_file: str | None = None
    adds = 0
    dels = 0

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            if current_file is not None and (adds > 0 or dels > 0):
                files.append((current_file, adds, dels))
            # Extract path from "diff --git a/path b/path"
            m = re.search(r"diff --git a/([^\s]+)", line)
            current_file = _normalize_path(m.group(1)) if m else ""
            adds = 0
            dels = 0
        elif line.startswith("--- "):
            continue
        elif line.startswith("+++ "):
            if current_file is None:
                current_file = _normalize_path(line[4:].strip())
            continue
        elif line.startswith("@@"):
            continue
        elif len(line) >= 2 and line[0] == "+" and not line.startswith("+++"):
            adds += 1
        elif len(line) >= 2 and line[0] == "-" and not line.startswith("---"):
            dels += 1

    if current_file is not None and (adds > 0 or dels > 0):
        files.append((current_file, adds, dels))

    return files


@dataclass
class BoundaryCheckResult:
    """Result of patch boundary enforcement check."""

    passed: bool
    violations: list[str] = field(default_factory=list)


def check_boundary(
    patch_diff: str,
    target_file: str,
) -> BoundaryCheckResult:
    """
    Enforce patch boundary limits.

    Args:
        patch_diff: Unified diff string.
        target_file: Expected target file path (relative to repo root).

    Returns:
        BoundaryCheckResult with passed=True if all limits satisfied,
        else passed=False and violations list.
    """
    violations: list[str] = []

    files = _parse_diff(patch_diff)
    target_norm = target_file.replace("\\", "/").lstrip("/")

    # 1. Only single file
    if len(files) == 0:
        violations.append("Patch contains no file changes")
    elif len(files) > 1:
        fnames = ", ".join(f[0] for f in files)
        violations.append(f"Only single file may be edited; found {len(files)}: {fnames}")

    # 2. Target file must match
    if files and len(files) == 1:
        changed_path = files[0][0]
        if changed_path != target_norm and not changed_path.endswith("/" + target_norm):
            violations.append(f"Patch modifies '{changed_path}' but target is '{target_norm}'")

    # 3. Max 40 lines changed
    total_adds = sum(f[1] for f in files)
    total_dels = sum(f[2] for f in files)
    total_changed = total_adds + total_dels
    if total_changed > MAX_LINES_CHANGED:
        violations.append(
            f"Exceeds max {MAX_LINES_CHANGED} lines changed (additions + deletions); got {total_changed}"
        )

    # 4 & 5. No forbidden paths
    for path, _, _ in files:
        if _is_forbidden(path):
            violations.append(f"Changes to excluded path not allowed: {path}")

    return BoundaryCheckResult(
        passed=len(violations) == 0,
        violations=violations,
    )
