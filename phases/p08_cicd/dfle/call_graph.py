"""
Function call graph for a Python repository.

Uses the AST index as input; extracts function calls from source
and builds a directed graph (caller -> callees) with lookup support.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


def _node_id(filename: str, name: str, line: int) -> str:
    """Canonical ID for a function (matches log_parser failure_site format)."""
    return f"{filename}:{line}:{name}"


class _CallCollector(ast.NodeVisitor):
    """Collect names of called functions from a function body."""

    def __init__(self) -> None:
        self.calls: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        name = _callable_name(node.func)
        if name:
            self.calls.add(name)
        self.generic_visit(node)


def _callable_name(node: ast.expr) -> str | None:
    """Extract the callable name from a Call's func node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _function_bodies(root: Path, filename: str) -> Iterator[tuple[str, int, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Parse file and yield (name, line, node) for each function def."""
    path = root / filename
    if not path.exists():
        return
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node.lineno, node


def _calls_in_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Extract all called names from a function's body."""
    collector = _CallCollector()
    for stmt in node.body:
        collector.visit(stmt)
    return collector.calls


def build_call_graph(
    index: dict[str, dict],
    root: str | Path,
) -> CallGraph:
    """
    Build a call graph from an AST index and source files.

    Args:
        index: AST index from ast_index.build_index or from_dict.
        root: Path to the repository root (for reading source files).

    Returns:
        CallGraph with caller->callee edges.
    """
    root_path = Path(root).resolve()
    callees: dict[str, list[str]] = {}

    for filename, entry in index.items():
        path = root_path / filename
        if not path.exists():
            continue

        func_map: dict[tuple[str, int], ast.FunctionDef | ast.AsyncFunctionDef] = {}
        for name, line, node in _function_bodies(root_path, filename):
            func_map[(name, line)] = node

        for f in entry.get("functions", []):
            fname = f.get("name")
            fline = f.get("line")
            if fname is None or fline is None:
                continue
            key = (str(fname), int(fline))
            node = func_map.get(key)
            if not node:
                continue

            node_id = _node_id(filename, fname, fline)
            calls = _calls_in_function(node)
            callees[node_id] = sorted(calls) if calls else []

    # Build reverse index: callee_name -> [caller_ids]
    callers: dict[str, list[str]] = {}
    for caller_id, called_names in callees.items():
        for callee in called_names:
            callers.setdefault(callee, []).append(caller_id)

    # Deduplicate and sort
    for k in callers:
        callers[k] = sorted(set(callers[k]))

    return CallGraph(callees=callees, callers=callers)


@dataclass
class CallGraph:
    """
    Directed call graph: caller -> callees.

    Node IDs use format "filename:line:function_name" (matches failure_site).
    Callee names are the invoked names (e.g. "foo", "bar") and may or may not
    resolve to indexed functions.
    """

    callees: dict[str, list[str]] = field(default_factory=dict)
    callers: dict[str, list[str]] = field(default_factory=dict)

    def lookup(self, node_id: str) -> tuple[list[str], list[str]]:
        """
        Return (callers, callees) for a function by its node ID.

        Args:
            node_id: "filename:line:function_name" or bare function name.

        Returns:
            (upstream callers, downstream callees)
        """
        callers = self.callers.get(node_id, [])
        callees = self.callees.get(node_id, [])
        return (list(callers), list(callees))

    def lookup_by_name(self, name: str) -> list[str]:
        """Return all node IDs whose function name matches (for disambiguation)."""
        return [nid for nid in self.callees if nid.endswith(f":{name}") or nid == name]

    def callers_of(self, name_or_id: str) -> list[str]:
        """Return all callers of the given function (by name or node ID)."""
        # Try full node_id first, then fall back to name-only matching
        if name_or_id in self.callers:
            return list(self.callers[name_or_id])
        key = name_or_id.rsplit(":", 2)[-1] if ":" in name_or_id else name_or_id
        return list(self.callers.get(key, []))

    def callees_of(self, node_id: str) -> list[str]:
        """Return all callees of the given function by node ID."""
        return list(self.callees.get(node_id, []))

    def to_dict(self) -> dict:
        """Serialize for Redis/JSON."""
        return {
            "callees": dict(self.callees),
            "callers": dict(self.callers),
        }

    @classmethod
    def from_dict(cls, data: dict) -> CallGraph:
        """Deserialize from dict."""
        return cls(
            callees={k: list(v) for k, v in data.get("callees", {}).items()},
            callers={k: list(v) for k, v in data.get("callers", {}).items()},
        )
