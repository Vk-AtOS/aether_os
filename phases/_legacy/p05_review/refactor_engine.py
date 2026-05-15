"""
Aether-One Refactor Engine

Enterprise-grade refactor operations:

- rename_symbol
- extract_function
- remove_unused_imports

Design goals:
- Pure Python + rope (for rename_symbol).
- Deterministic, safe, text-based transformations.
- Always return a structured RefactorResult with a human-readable diff.
"""

from __future__ import annotations

import ast
import difflib
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

try:
    from rope.base.project import Project
    from rope.base.libutils import path_to_resource
    from rope.refactor.rename import Rename
    ROPE_AVAILABLE = True
except Exception:
    ROPE_AVAILABLE = False


@dataclass
class RefactorResult:
    ok: bool
    applied: bool
    num_changed_files: int
    description: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _unified_diff(old: str, new: str, fromfile: str, tofile: str) -> str:
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=fromfile,
        tofile=tofile,
    )
    return "".join(diff)


def _offset_from_line_column(source: str, line: int, column: int) -> int:
    """
    Convert 1-based (line, column) into 0-based absolute offset.
    """
    if line < 1:
        line = 1
    lines = source.splitlines(keepends=True)
    if line > len(lines):
        line = len(lines)
    offset = sum(len(l) for l in lines[: line - 1])
    offset += max(column - 1, 0)
    return offset


# ---------------------------------------------------------------------------
# 1) Rename symbol (rope-backed)
# ---------------------------------------------------------------------------

def rename_symbol(
    project_root: str,
    file_path: str,
    line: int,
    column: int,
    new_name: str,
    apply: bool = False,
) -> RefactorResult:
    """
    Rename a symbol (function, class, variable) at a given location using rope.

    Args:
        project_root: Root of the project.
        file_path: Path to the file (absolute or relative to project_root).
        line: 1-based line number where the symbol is located.
        column: 1-based column within that line.
        new_name: New symbol name.
        apply: If True, write changes back to disk. Otherwise, dry-run.

    Returns:
        RefactorResult with diff in .description.
    """
    if not ROPE_AVAILABLE:
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error="rope is not installed; run `pip install rope`.",
        )

    project_abs = os.path.abspath(os.path.expanduser(project_root))
    if not os.path.isdir(project_abs):
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error=f"project_root is not a directory: {project_abs}",
        )

    file_abs = os.path.abspath(
        file_path if os.path.isabs(file_path) else os.path.join(project_abs, file_path)
    )
    if not os.path.isfile(file_abs):
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error=f"file_path is not a file: {file_abs}",
        )

    try:
        source = _read_text(file_abs)
    except Exception as e:
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error=f"failed to read file: {e}",
        )

    try:
        proj = Project(project_abs)
    except Exception as e:
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error=f"failed to open rope project: {e}",
        )

    try:
        resource = path_to_resource(proj, file_abs)
        offset = _offset_from_line_column(source, line, column)
        renamer = Rename(proj, resource, offset)
        changes = renamer.get_changes(new_name)
    except Exception as e:
        proj.close()
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error=f"rename failed: {e}",
        )

    # Build a textual description from rope's changes
    description_parts: List[str] = []
    num_files = 0
    try:
        for res in changes.get_changed_resources():
            num_files += 1
            old_source = res.read()
            new_source = changes.get_new_contents(res)
            rel = os.path.relpath(res.real_path, project_abs)
            description_parts.append(
                _unified_diff(old_source, new_source, fromfile=f"a/{rel}", tofile=f"b/{rel}")
            )
    except Exception:
        # Fall back to rope's internal description
        try:
            description_parts.append(str(changes.get_description()))
        except Exception:
            description_parts.append("rename_symbol: changes prepared (diff unavailable)")

    description = "\n".join(p for p in description_parts if p.strip())

    applied = False
    if apply:
        try:
            proj.do(changes)
            applied = True
        except Exception as e:
            proj.close()
            return RefactorResult(
                ok=False,
                applied=False,
                num_changed_files=num_files,
                description=description,
                error=f"failed to apply changes: {e}",
            )

    proj.close()
    return RefactorResult(
        ok=True,
        applied=applied,
        num_changed_files=num_files,
        description=description,
        error=None,
    )


# ---------------------------------------------------------------------------
# 2) Extract function (string-based refactor)
# ---------------------------------------------------------------------------

def extract_function(
    project_root: str,
    file_path: str,
    start_line: int,
    end_line: int,
    new_name: str,
    apply: bool = False,
) -> RefactorResult:
    """
    Extract a contiguous block of code into a new top-level function.

    This is conservative and text-based:
      - It assumes start_line..end_line are within one logical block.
      - It inserts `def new_name():` near the end of the file.
      - It replaces the original block with `new_name()` call at the same indent.

    The caller should ensure:
      - The block is valid Python.
      - Any variables it needs are available via closure/global scope.

    Args:
        project_root: Project root directory.
        file_path: File to modify (abs or relative).
        start_line: 1-based start line of block to extract.
        end_line: 1-based end line of block to extract.
        new_name: Name for the new function.
        apply: If True, write changes.

    Returns:
        RefactorResult with a unified diff in .description.
    """
    project_abs = os.path.abspath(os.path.expanduser(project_root))
    file_abs = os.path.abspath(
        file_path if os.path.isabs(file_path) else os.path.join(project_abs, file_path)
    )

    if not os.path.isfile(file_abs):
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error=f"file_path is not a file: {file_abs}",
        )

    try:
        source = _read_text(file_abs)
    except Exception as e:
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error=f"failed to read file: {e}",
        )

    lines = source.splitlines(keepends=True)
    if not (1 <= start_line <= len(lines)) or not (1 <= end_line <= len(lines)):
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error="start_line/end_line out of range",
        )
    if start_line > end_line:
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error="start_line must be <= end_line",
        )

    block = lines[start_line - 1 : end_line]
    if not block:
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error="no lines selected for extraction",
        )

    # Compute indentation from the first non-empty line in the block
    indent_str = ""
    for l in block:
        stripped = l.lstrip()
        if stripped:
            indent_len = len(l) - len(stripped)
            indent_str = l[:indent_len]
            break

    def _indent_block(body_lines: List[str]) -> List[str]:
        indented: List[str] = []
        for l in body_lines:
            if l.strip() == "":
                indented.append("    \n")
            else:
                # Remove the original block indentation if present
                if indent_str and l.startswith(indent_str):
                    core = l[len(indent_str) :]
                else:
                    core = l
                indented.append("    " + core.lstrip())
        return indented

    new_func_lines: List[str] = []
    new_func_lines.append("\n\n")
    new_func_lines.append(f"def {new_name}():\n")
    new_func_lines.extend(_indent_block(block))

    # Replace original block with a function call at same indentation
    call_line = indent_str + f"{new_name}()\n"
    new_lines = []
    new_lines.extend(lines[: start_line - 1])
    new_lines.append(call_line)
    new_lines.extend(lines[end_line:])

    new_source = "".join(new_lines + new_func_lines)

    # Validate syntax of new source; if invalid, abort.
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error=f"extracted code results in invalid syntax: {e}",
        )

    diff = _unified_diff(source, new_source, fromfile=file_abs, tofile=file_abs)

    if apply:
        try:
            _write_text(file_abs, new_source)
        except Exception as e:
            return RefactorResult(
                ok=False,
                applied=False,
                num_changed_files=1,
                description=diff,
                error=f"failed to write file: {e}",
            )

    return RefactorResult(
        ok=True,
        applied=apply,
        num_changed_files=1,
        description=diff,
        error=None,
    )


# ---------------------------------------------------------------------------
# 3) Remove unused imports (conservative)
# ---------------------------------------------------------------------------

def _collect_imports(tree: ast.AST) -> List[Tuple[ast.AST, List[str]]]:
    imports: List[Tuple[ast.AST, List[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names: List[str] = []
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                names.append(name)
            imports.append((node, names))
        elif isinstance(node, ast.ImportFrom):
            names = []
            for alias in node.names:
                name = alias.asname or alias.name
                names.append(name)
            imports.append((node, names))
    return imports


def _collect_used_names(tree: ast.AST) -> List[str]:
    used: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.append(node.id)
    return used


def remove_unused(
    project_root: str,
    file_path: str,
    apply: bool = False,
) -> RefactorResult:
    """
    Remove obviously-unused imports from a file.

    - Only removes entire import statements where *all* imported names are unused.
    - Does not attempt advanced analysis; conservative to avoid breaking code.
    """
    project_abs = os.path.abspath(os.path.expanduser(project_root))
    file_abs = os.path.abspath(
        file_path if os.path.isabs(file_path) else os.path.join(project_abs, file_path)
    )

    if not os.path.isfile(file_abs):
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error=f"file_path is not a file: {file_abs}",
        )

    try:
        source = _read_text(file_abs)
    except Exception as e:
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error=f"failed to read file: {e}",
        )

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error=f"cannot parse file: {e}",
        )

    imports = _collect_imports(tree)
    used_names = set(_collect_used_names(tree))

    # Determine which import nodes are fully unused
    to_remove: List[ast.AST] = []
    for node, names in imports:
        if all(name not in used_names for name in names):
            to_remove.append(node)

    if not to_remove:
        return RefactorResult(
            ok=True,
            applied=False,
            num_changed_files=0,
            description="No unused imports found.",
            error=None,
        )

    lines = source.splitlines(keepends=True)
    remove_indices: set[int] = set()

    for node in to_remove:
        lineno = getattr(node, "lineno", None)
        end_lineno = getattr(node, "end_lineno", None)
        if lineno is None:
            continue
        if end_lineno is None:
            end_lineno = lineno
        # Convert to 0-based indices
        for i in range(lineno - 1, end_lineno):
            if 0 <= i < len(lines):
                remove_indices.add(i)

    new_lines = [l for i, l in enumerate(lines) if i not in remove_indices]
    new_source = "".join(new_lines)

    # Validate syntax after removal.
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        return RefactorResult(
            ok=False,
            applied=False,
            num_changed_files=0,
            description="",
            error=f"removing imports caused invalid syntax: {e}",
        )

    diff = _unified_diff(source, new_source, fromfile=file_abs, tofile=file_abs)

    if apply:
        try:
            _write_text(file_abs, new_source)
        except Exception as e:
            return RefactorResult(
                ok=False,
                applied=False,
                num_changed_files=1,
                description=diff,
                error=f"failed to write file: {e}",
            )

    return RefactorResult(
        ok=True,
        applied=apply,
        num_changed_files=1,
        description=diff,
        error=None,
    )

