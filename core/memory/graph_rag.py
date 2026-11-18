"""
Aether-One Offline Graph RAG (Repository Graph + Symbol Index)

Goal:
    Build a local, offline "graph view" of the repository that can answer:
      - Which files/modules are related to this file?
      - Where is a given symbol (function/class) defined?
      - What are the high-connectivity hubs?

This is a foundation for:
    - Repository-wide reasoning
    - Code navigation / onboarding
    - Future LLM-assisted RAG, entirely offline

The graph is built on-demand and kept in-memory; no DB writes here.

Public API:

    build_graph(project_path: str) -> dict
        Build full graph + symbol index.

    get_related_files(project_path: str, file_path: str, max_results: int = 10) -> dict
        Return nearest neighbors for the given file.

    find_symbol_definitions(project_path: str, symbol: str, max_results: int = 20) -> dict
        Return files and line numbers where the symbol is defined.
"""

from __future__ import annotations

import ast
import logging
import os
from dataclasses import dataclass, asdict
from typing import Dict, List, Set, Any

logger = logging.getLogger(__name__)


@dataclass
class SymbolDef:
    name: str
    kind: str  # "function" | "class"
    file_path: str
    lineno: int


@dataclass
class RepoGraph:
    project_path: str
    files: List[str]
    # module -> imports (top-level module names)
    module_imports: Dict[str, Set[str]]
    # file_path -> set of directly related file_paths (same module, imports, etc.)
    file_neighbors: Dict[str, Set[str]]
    # symbol name -> list of SymbolDef
    symbol_index: Dict[str, List[SymbolDef]]


# ----------- Helpers for walking and parsing -----------


def _iter_python_files(project_path: str) -> List[str]:
    py_files: List[str] = []
    for root, dirs, files in os.walk(project_path):
        # Skip snapshot and venv dirs
        if ".aetherone_snapshots" in root:
            continue
        if os.path.basename(root) in {".venv", "venv", "__pycache__"}:
            continue

        for name in files:
            if name.endswith(".py"):
                py_files.append(os.path.join(root, name))
    return py_files


def _module_name_from_path(project_path: str, file_path: str) -> str:
    rel = os.path.relpath(file_path, project_path)
    rel_wo_ext, _ = os.path.splitext(rel)
    parts: List[str] = []
    for part in rel_wo_ext.split(os.sep):
        if part == "__init__":
            continue
        parts.append(part)
    if not parts:
        return "__root__"
    return ".".join(parts)


def _parse_imports(file_path: str) -> List[str]:
    out: List[str] = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except Exception as e:
        logger.debug("_parse_imports failed for %s: %s", file_path, e)
        return out

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append(node.module.split(".")[0])
    return out


def _parse_symbol_defs(file_path: str) -> List[SymbolDef]:
    defs: List[SymbolDef] = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except Exception as e:
        logger.debug("_parse_symbol_defs failed for %s: %s", file_path, e)
        return defs

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            defs.append(
                SymbolDef(
                    name=node.name,
                    kind="function",
                    file_path=file_path,
                    lineno=getattr(node, "lineno", 1),
                )
            )
        elif isinstance(node, ast.AsyncFunctionDef):
            defs.append(
                SymbolDef(
                    name=node.name,
                    kind="function",
                    file_path=file_path,
                    lineno=getattr(node, "lineno", 1),
                )
            )
        elif isinstance(node, ast.ClassDef):
            defs.append(
                SymbolDef(
                    name=node.name,
                    kind="class",
                    file_path=file_path,
                    lineno=getattr(node, "lineno", 1),
                )
            )
    return defs


# ----------- Graph construction -----------


def build_graph(project_path: str) -> Dict[str, Any]:
    project_abs = os.path.abspath(os.path.expanduser(project_path))
    py_files = _iter_python_files(project_abs)

    module_imports: Dict[str, Set[str]] = {}
    module_to_files: Dict[str, Set[str]] = {}
    symbol_index: Dict[str, List[SymbolDef]] = {}

    # First pass: module imports + symbol defs
    for path in py_files:
        mod_name = _module_name_from_path(project_abs, path)
        imports = _parse_imports(path)
        module_imports.setdefault(mod_name, set()).update(imports)
        module_to_files.setdefault(mod_name, set()).add(path)

        defs = _parse_symbol_defs(path)
        for d in defs:
            symbol_index.setdefault(d.name, []).append(d)

    # Build a simple file-level neighbor graph:
    # - same module group
    # - modules that import each other
    file_neighbors: Dict[str, Set[str]] = {p: set() for p in py_files}

    # Same module group neighbors
    for files in module_to_files.values():
        files_list = list(files)
        for i, f1 in enumerate(files_list):
            for f2 in files_list[i + 1 :]:
                file_neighbors[f1].add(f2)
                file_neighbors[f2].add(f1)

    # Module import relationships -> file neighbors
    # If module A imports module B, connect all files in A with all in B.
    for mod, imports in module_imports.items():
        files_mod = module_to_files.get(mod, set())
        for target_mod in imports:
            files_target = module_to_files.get(target_mod, set())
            for f1 in files_mod:
                for f2 in files_target:
                    if f1 == f2:
                        continue
                    file_neighbors[f1].add(f2)
                    file_neighbors[f2].add(f1)

    graph = RepoGraph(
        project_path=project_abs,
        files=py_files,
        module_imports=module_imports,
        file_neighbors=file_neighbors,
        symbol_index=symbol_index,
    )

    # Serialize to dict for external use
    return {
        "project_path": graph.project_path,
        "files": graph.files,
        "module_imports": {k: sorted(list(v)) for k, v in graph.module_imports.items()},
        "file_neighbors": {k: sorted(list(v)) for k, v in graph.file_neighbors.items()},
        "symbol_index": {
            name: [asdict(d) for d in defs] for name, defs in graph.symbol_index.items()
        },
    }


def get_related_files(
    project_path: str,
    file_path: str,
    max_results: int = 10,
) -> Dict[str, Any]:
    """
    Return nearest neighbors for the given file based on the file_neighbors graph.
    """
    project_abs = os.path.abspath(os.path.expanduser(project_path))
    file_abs = os.path.abspath(os.path.expanduser(file_path))

    graph = build_graph(project_abs)
    neighbors_all = graph["file_neighbors"].get(file_abs, [])

    neighbors = neighbors_all[:max_results]

    return {
        "project_path": project_abs,
        "file_path": file_abs,
        "neighbors": neighbors,
        "total_neighbors": len(neighbors_all),
        "max_results": max_results,
    }


def find_symbol_definitions(
    project_path: str,
    symbol: str,
    max_results: int = 20,
) -> Dict[str, Any]:
    """
    Return symbol definition locations (file + line) for a given symbol name.
    """
    project_abs = os.path.abspath(os.path.expanduser(project_path))
    graph = build_graph(project_abs)

    defs = graph["symbol_index"].get(symbol, [])
    if len(defs) > max_results:
        defs = defs[:max_results]

    return {
        "project_path": project_abs,
        "symbol": symbol,
        "definitions": defs,
        "max_results": max_results,
    }

