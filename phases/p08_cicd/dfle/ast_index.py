"""
Incremental AST index for a Python repository.

Builds an index of function and class definitions per file,
supports incremental updates, and serializes to dict for Redis caching.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileIndexEntry:
    """Per-file index: functions and classes with line numbers."""

    filename: str
    functions: list[dict[str, str | int]] = field(default_factory=list)
    classes: list[dict[str, str | int]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "functions": list(self.functions),
            "classes": list(self.classes),
        }

    @classmethod
    def from_dict(cls, data: dict) -> FileIndexEntry:
        return cls(
            filename=data["filename"],
            functions=[dict(f) for f in data.get("functions", [])],
            classes=[dict(c) for c in data.get("classes", [])],
        )


class _IndexVisitor(ast.NodeVisitor):
    """Extract function and class definitions with line numbers."""

    def __init__(self) -> None:
        self.functions: list[dict[str, str | int]] = []
        self.classes: list[dict[str, str | int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append({"name": node.name, "line": node.lineno})
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.functions.append({"name": node.name, "line": node.lineno})
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append({"name": node.name, "line": node.lineno})
        self.generic_visit(node)


def _index_file(path: Path, root: Path) -> FileIndexEntry | None:
    """Parse a single Python file and return its index entry."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return None

    visitor = _IndexVisitor()
    visitor.visit(tree)

    rel_path = path.relative_to(root).as_posix()
    return FileIndexEntry(
        filename=rel_path,
        functions=visitor.functions,
        classes=visitor.classes,
    )


def _collect_py_files(root: Path, exclude_dirs: frozenset[str] | None = None) -> list[Path]:
    """Recursively collect all .py files under root, excluding given dir names."""
    skip = exclude_dirs or frozenset(("venv", ".venv", "__pycache__", ".git", "node_modules"))
    paths: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in skip for part in path.relative_to(root).parts):
            continue
        paths.append(path)
    return sorted(paths)


def build_index(root: str | Path) -> dict[str, dict]:
    """
    Build AST index from a directory of Python files.

    Args:
        root: Path to the repository root (or directory to index).

    Returns:
        Dict mapping relative file path -> FileIndexEntry as dict,
        ready for Redis or JSON serialization.
    """
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        return {}

    index: dict[str, dict] = {}
    for path in _collect_py_files(root_path):
        entry = _index_file(path, root_path)
        if entry:
            index[entry.filename] = entry.to_dict()
    return index


def update_index(
    existing: dict[str, dict],
    root: str | Path,
    changed_files: list[str],
) -> dict[str, dict]:
    """
    Incremental update: reparse only the given changed files and merge.

    Args:
        existing: Current index (from build_index or from_dict).
        root: Path to the repository root.
        changed_files: List of relative paths to files that changed.

    Returns:
        Updated index dict. Changed files are replaced; others unchanged.
        Files that fail to parse or no longer exist are removed from the index.
    """
    root_path = Path(root).resolve()
    result = dict(existing)

    for rel_path in changed_files:
        path = root_path / rel_path
        if not path.exists() or not path.suffix == ".py":
            result.pop(rel_path, None)
            continue

        entry = _index_file(path, root_path)
        if entry:
            result[rel_path] = entry.to_dict()
        else:
            result.pop(rel_path, None)

    return result


def to_dict(index: dict[str, dict]) -> dict:
    """
    Serialize index to a plain dict for Redis/JSON.

    The index is already dict-based; this normalizes the shape and ensures
    deep-copy compatibility (no non-serializable objects).
    """
    return {k: dict(v) for k, v in index.items()}


def from_dict(data: dict) -> dict[str, dict]:
    """
    Deserialize index from dict (e.g., from Redis).

    Args:
        data: Dict from to_dict or Redis GET.

    Returns:
        Index as dict mapping filename -> FileIndexEntry dict.
    """
    if not data:
        return {}
    return {k: dict(v) for k, v in data.items()}
