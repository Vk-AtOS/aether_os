"""
Aether-One Time Travel Snapshot Explorer

Purpose
-------
Safe, enterprise-grade snapshot system for Aether-One projects:

- Create project snapshots (code + config) under .aetherone_snapshots/
- List and inspect snapshots
- Compare snapshots against the current workspace (what changed?)
- Materialize snapshots into separate directories (non-destructive restore)
- Provide an explicit, guarded entrypoint for in-place restore

This is designed to be wired into:

- Live Guardian (auto-snapshots before risky changes)
- Fix engine (snapshot-before-fix)
- Temporal risk analysis (snapshot lineage)
- Dashboard (time travel view)

Snapshots are *file-level copies* within the same filesystem, not git commits.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths & utilities
# ---------------------------------------------------------------------------


def _normalize_project_path(project_path: str) -> str:
    return os.path.abspath(os.path.expanduser(project_path))


def snapshots_root(project_path: str) -> str:
    """
    Root directory where snapshots are stored for a project.
    """
    project_abs = _normalize_project_path(project_path)
    return os.path.join(project_abs, ".aetherone_snapshots")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _matches_any(patterns: List[str], rel_path: str) -> bool:
    rel_posix = rel_path.replace(os.sep, "/")
    for patt in patterns:
        if fnmatch.fnmatch(rel_posix, patt):
            return True
    return False


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SnapshotInfo:
    """
    Metadata for a single snapshot.
    """

    snapshot_id: str
    project_path: str
    root_path: str
    created_at: str
    label: Optional[str]
    includes: List[str]
    excludes: List[str]
    file_count: int
    approximate_size_bytes: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SnapshotDiffEntry:
    """
    Single file-level diff entry between snapshot and workspace.

    status:
        - "added"    : exists now, not in snapshot
        - "removed"  : existed in snapshot, not now
        - "modified" : exists in both, content differs
        - "same"     : exists in both, content identical
    """

    status: str
    path: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SnapshotDiffSummary:
    """
    Aggregated comparison of snapshot vs current workspace.
    """

    snapshot_id: str
    project_path: str
    compared_at: str
    added: List[SnapshotDiffEntry]
    removed: List[SnapshotDiffEntry]
    modified: List[SnapshotDiffEntry]
    same: List[SnapshotDiffEntry]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_DEFAULT_EXCLUDES = [
    ".git/*",
    ".venv/*",
    "venv/*",
    "__pycache__/*",
    "*.pyc",
    ".DS_Store",
    ".aetherone_snapshots/*",
    ".aetherone.db",
    ".aetherone_audit.log",
    ".aetherone_telemetry.log",
    ".aetherone_policy_suggestions.json",
]


def _walk_project_files(
    project_path: str,
    includes: Optional[List[str]] = None,
    excludes: Optional[List[str]] = None,
) -> List[str]:
    """
    Return a list of *relative* file paths under project_path,
    filtered by include/exclude globs.
    """
    project_abs = _normalize_project_path(project_path)
    includes = includes or []
    excludes = (excludes or []) + _DEFAULT_EXCLUDES

    paths: List[str] = []

    for root, dirs, files in os.walk(project_abs):
        rel_root = os.path.relpath(root, project_abs)
        rel_root_posix = rel_root.replace(os.sep, "/")

        # Handle root "." specially
        if rel_root == ".":
            rel_root_posix = ""

        # Filter dirs
        kept_dirs = []
        for d in dirs:
            rel_dir = f"{rel_root_posix}/{d}" if rel_root_posix else d
            if _matches_any(excludes, rel_dir + "/*"):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        # Files
        for f in files:
            rel_path = f"{rel_root_posix}/{f}" if rel_root_posix else f
            if _matches_any(excludes, rel_path):
                continue
            if includes:
                if not _matches_any(includes, rel_path):
                    continue
            paths.append(rel_path)

    return sorted(paths)


def _snapshot_dir_for_id(project_path: str, snapshot_id: str) -> str:
    return os.path.join(snapshots_root(project_path), snapshot_id)


def _metadata_path(snapshot_root: str) -> str:
    return os.path.join(snapshot_root, "snapshot.json")


def _compute_file_hash(path: str) -> str:
    """
    Compute SHA256 for the given file (used for diff).
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_snapshot_metadata(snapshot_root: str) -> SnapshotInfo:
    with open(_metadata_path(snapshot_root), "r", encoding="utf-8") as f:
        data = json.load(f)
    return SnapshotInfo(**data)


# ---------------------------------------------------------------------------
# Snapshot creation & listing
# ---------------------------------------------------------------------------


def create_snapshot(
    project_path: str,
    *,
    label: Optional[str] = None,
    includes: Optional[List[str]] = None,
    excludes: Optional[List[str]] = None,
) -> SnapshotInfo:
    """
    Create a new snapshot of the given project.

    Snapshots live under:
        <project>/.aetherone_snapshots/<snapshot_id>/

    This function:
        - Gathers files with include/exclude filters
        - Copies them into the snapshot directory
        - Writes snapshot.json metadata
    """
    project_abs = _normalize_project_path(project_path)
    root = snapshots_root(project_abs)
    os.makedirs(root, exist_ok=True)

    # Simple unique ID: timestamp + short counter
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_id = ts
    snapshot_id = base_id
    idx = 1
    while os.path.exists(_snapshot_dir_for_id(project_abs, snapshot_id)):
        snapshot_id = f"{base_id}_{idx}"
        idx += 1

    snap_root = _snapshot_dir_for_id(project_abs, snapshot_id)
    os.makedirs(snap_root, exist_ok=True)

    rel_files = _walk_project_files(project_abs, includes=includes, excludes=excludes)
    total_size = 0
    file_count = 0

    for rel in rel_files:
        src = os.path.join(project_abs, rel)
        dst = os.path.join(snap_root, rel)

        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

        try:
            total_size += os.path.getsize(src)
        except OSError as e:
            logger.warning("snapshot/manager: could not get file size for %s: %s", src, e)
        file_count += 1

    info = SnapshotInfo(
        snapshot_id=snapshot_id,
        project_path=project_abs,
        root_path=snap_root,
        created_at=_utc_now_iso(),
        label=label,
        includes=includes or [],
        excludes=excludes or [],
        file_count=file_count,
        approximate_size_bytes=total_size,
    )

    with open(_metadata_path(snap_root), "w", encoding="utf-8") as f:
        json.dump(info.to_dict(), f, indent=2, ensure_ascii=False, sort_keys=True)

    return info


def list_snapshots(project_path: str) -> List[SnapshotInfo]:
    """
    List all snapshots for a project, sorted by creation time (derived from ID).
    """
    project_abs = _normalize_project_path(project_path)
    root = snapshots_root(project_abs)
    if not os.path.isdir(root):
        return []

    infos: List[SnapshotInfo] = []
    for entry in sorted(os.listdir(root)):
        snap_root = os.path.join(root, entry)
        if not os.path.isdir(snap_root):
            continue
        meta_path = _metadata_path(snap_root)
        if not os.path.exists(meta_path):
            continue
        try:
            info = _load_snapshot_metadata(snap_root)
            infos.append(info)
        except Exception:
            continue

    # Already sorted lexicographically by ID (which embeds timestamp)
    return infos


def get_snapshot(project_path: str, snapshot_id: str) -> Optional[SnapshotInfo]:
    """
    Get metadata for a specific snapshot_id, or None if not found.
    """
    project_abs = _normalize_project_path(project_path)
    snap_root = _snapshot_dir_for_id(project_abs, snapshot_id)
    if not os.path.isdir(snap_root):
        return None
    meta_path = _metadata_path(snap_root)
    if not os.path.exists(meta_path):
        return None
    try:
        return _load_snapshot_metadata(snap_root)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Comparison & time travel
# ---------------------------------------------------------------------------


def compare_snapshot_to_workspace(
    project_path: str,
    snapshot_id: str,
    *,
    includes: Optional[List[str]] = None,
    excludes: Optional[List[str]] = None,
) -> SnapshotDiffSummary:
    """
    Compare a snapshot against the current workspace.

    Returns a SnapshotDiffSummary that lists:
        - added   (in workspace, not in snapshot)
        - removed (in snapshot, not in workspace)
        - modified
        - same
    """
    project_abs = _normalize_project_path(project_path)
    snap_info = get_snapshot(project_abs, snapshot_id)
    if not snap_info:
        raise ValueError(f"Snapshot {snapshot_id!r} not found for project {project_abs!r}.")

    snap_root = snap_info.root_path

    # Determine files in snapshot and workspace
    snap_files = _walk_project_files(snap_root, includes=includes, excludes=excludes)
    ws_files = _walk_project_files(project_abs, includes=includes, excludes=excludes)

    snap_set = set(snap_files)
    ws_set = set(ws_files)

    added_paths = ws_set - snap_set
    removed_paths = snap_set - ws_set
    common_paths = ws_set & snap_set

    added = [SnapshotDiffEntry(status="added", path=p) for p in sorted(added_paths)]
    removed = [SnapshotDiffEntry(status="removed", path=p) for p in sorted(removed_paths)]

    modified: List[SnapshotDiffEntry] = []
    same: List[SnapshotDiffEntry] = []

    for rel in sorted(common_paths):
        snap_file = os.path.join(snap_root, rel)
        ws_file = os.path.join(project_abs, rel)
        try:
            snap_hash = _compute_file_hash(snap_file)
            ws_hash = _compute_file_hash(ws_file)
        except Exception:
            # If we can't read one of them, treat as modified
            modified.append(SnapshotDiffEntry(status="modified", path=rel))
            continue

        if snap_hash == ws_hash:
            same.append(SnapshotDiffEntry(status="same", path=rel))
        else:
            modified.append(SnapshotDiffEntry(status="modified", path=rel))

    return SnapshotDiffSummary(
        snapshot_id=snapshot_id,
        project_path=project_abs,
        compared_at=_utc_now_iso(),
        added=added,
        removed=removed,
        modified=modified,
        same=same,
    )


def materialize_snapshot(
    project_path: str,
    snapshot_id: str,
    destination_path: str,
    *,
    overwrite: bool = False,
) -> SnapshotInfo:
    """
    Copy a snapshot into another directory (non-destructive restore).

    This is the safest time travel operation:

        - Does NOT touch the live project directory.
        - Creates/uses destination_path as a separate tree.
    """
    project_abs = _normalize_project_path(project_path)
    snap_info = get_snapshot(project_abs, snapshot_id)
    if not snap_info:
        raise ValueError(f"Snapshot {snapshot_id!r} not found for project {project_abs!r}.")

    snap_root = snap_info.root_path
    dest_abs = os.path.abspath(os.path.expanduser(destination_path))

    if os.path.exists(dest_abs):
        if not overwrite and os.listdir(dest_abs):
            raise ValueError(
                f"Destination path {dest_abs!r} exists and is not empty. "
                f"Pass overwrite=True to allow copying into it."
            )
    else:
        os.makedirs(dest_abs, exist_ok=True)

    for root, dirs, files in os.walk(snap_root):
        rel_root = os.path.relpath(root, snap_root)
        if rel_root == ".":
            rel_root = ""
        for d in dirs:
            dest_dir = os.path.join(dest_abs, rel_root, d) if rel_root else os.path.join(dest_abs, d)
            os.makedirs(dest_dir, exist_ok=True)
        for f in files:
            if f == "snapshot.json":
                continue
            rel_path = os.path.join(rel_root, f) if rel_root else f
            src = os.path.join(root, f)
            dst = os.path.join(dest_abs, rel_root, f) if rel_root else os.path.join(dest_abs, f)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

    return snap_info


def restore_snapshot_inplace(
    project_path: str,
    snapshot_id: str,
    *,
    includes: Optional[List[str]] = None,
    excludes: Optional[List[str]] = None,
    force: bool = False,
) -> SnapshotInfo:
    """
    In-place restore: copy snapshot contents back into the project directory.

    WARNING:
        - This overwrites files in the project directory that are present
          in the snapshot (subject to include/exclude filters).
        - It does NOT delete extra files that exist only in the workspace.

    This is intended to be wrapped by a zero-trust approval workflow
    in higher layers. `force=True` is required to make it explicit.
    """
    if not force:
        raise ValueError(
            "restore_snapshot_inplace requires force=True to avoid accidental destructive changes."
        )

    project_abs = _normalize_project_path(project_path)
    snap_info = get_snapshot(project_abs, snapshot_id)
    if not snap_info:
        raise ValueError(f"Snapshot {snapshot_id!r} not found for project {project_abs!r}.")

    snap_root = snap_info.root_path

    # We reuse _walk_project_files but rooted at snapshot
    rel_files = _walk_project_files(snap_root, includes=includes, excludes=excludes)

    for rel in rel_files:
        src = os.path.join(snap_root, rel)
        dst = os.path.join(project_abs, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

    return snap_info

