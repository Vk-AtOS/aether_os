"""
Aether-One Monorepo Reasoning Accelerators

Purpose
-------
Give Aether-One an internal "map" of a monorepo:

- Identify components (services, libraries, apps) within a repo.
- Detect internal dependencies between components.
- Provide change-impact reasoning:
  - If these files changed, which components are touched?
  - Which other components depend on them (blast radius)?
  - Which tests should be considered high priority?

This module is:
- Pure Python, offline, and deterministic.
- Designed to work on single repos as well as large monorepos.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, Iterable, List, Set, Tuple


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Component:
    """
    One logical component in a monorepo.

    Examples:
        - Python service (FastAPI backend)
        - Shared library package
        - Node/Next.js app
        - Firmware project
    """

    name: str
    kind: str  # e.g. "python_pkg", "node_app", "firmware", "generic"
    root_relpath: str
    languages: List[str]
    test_paths: List[str] = field(default_factory=list)
    doc_paths: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DependencyEdge:
    """
    Directed dependency between two components.
    """

    from_component: str
    to_component: str
    reason: str  # e.g. "python_import:aetherone", "js_dep", "shared_folder"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MonorepoModel:
    """
    Overall monorepo model: components + dependencies.
    """

    root_path: str
    components: List[Component]
    dependencies: List[DependencyEdge]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeImpactPlan:
    """
    Result of analysing a set of changed files.

    Fields:
        changed_files:
            Input changed file paths (relative to repo root).

        touched_components:
            Components that directly own at least one changed file.

        directly_impacted_components:
            Same as touched_components (alias for clarity).

        transitively_impacted_components:
            Components that depend (directly or indirectly) on touched ones.

        recommended_test_paths:
            High-priority test files / directories to run first.
    """

    changed_files: List[str]
    touched_components: List[str]
    directly_impacted_components: List[str]
    transitively_impacted_components: List[str]
    recommended_test_paths: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Basic filesystem helpers
# ---------------------------------------------------------------------------


def _normalize_root(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _should_skip_dir(dirname: str) -> bool:
    lower = dirname.lower()
    if lower in {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__"}:
        return True
    if lower.startswith(".pytest_cache"):
        return True
    return False


def _is_test_path(relpath: str) -> bool:
    rel = relpath.replace("\\", "/")
    base = os.path.basename(rel)
    if "tests/" in rel or rel.startswith("tests/"):
        return True
    if base.startswith("test_") or base.endswith("_test.py") or base.endswith("_tests.py"):
        return True
    return False


def _is_doc_path(relpath: str) -> bool:
    rel = relpath.replace("\\", "/").lower()
    if "docs/" in rel:
        return True
    _, ext = os.path.splitext(rel)
    if ext in {".md", ".rst", ".adoc"}:
        return True
    return False


# ---------------------------------------------------------------------------
# Component detection
# ---------------------------------------------------------------------------


def _detect_top_level_components(root_path: str) -> List[Component]:
    """
    Heuristic component detection:

    - Top-level directories under the repo root become candidates.
    - Also consider a core Python package at the root (e.g. 'aetherone/').
    - Classify each component by kind/language based on files inside.
    """
    root_abs = _normalize_root(root_path)
    entries = os.listdir(root_abs)

    candidate_dirs: List[str] = []

    for name in entries:
        full = os.path.join(root_abs, name)
        if not os.path.isdir(full):
            continue
        if _should_skip_dir(name):
            continue
        candidate_dirs.append(name)

    components: List[Component] = []

    for dirname in sorted(candidate_dirs):
        full_dir = os.path.join(root_abs, dirname)
        rel_dir = dirname

        languages: Set[str] = set()
        test_paths: List[str] = []
        doc_paths: List[str] = []

        has_init = False
        has_package_json = False
        has_c = False

        for dirpath, dirnames, filenames in os.walk(full_dir):
            dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
            for fn in filenames:
                relpath = os.path.relpath(os.path.join(dirpath, fn), root_abs)
                rel_unix = relpath.replace("\\", "/")
                _, ext = os.path.splitext(fn)

                if ext == ".py":
                    languages.add("python")
                    if fn == "__init__.py":
                        has_init = True
                elif ext in {".ts", ".tsx", ".js", ".jsx"}:
                    languages.add("javascript")
                elif ext in {".c", ".h"}:
                    languages.add("c")
                    has_c = True

                if fn == "package.json":
                    has_package_json = True

                if _is_test_path(rel_unix):
                    test_paths.append(rel_unix)
                if _is_doc_path(rel_unix):
                    doc_paths.append(rel_unix)

        # Decide kind
        if has_package_json and "javascript" in languages:
            kind = "node_app"
        elif has_init and "python" in languages:
            kind = "python_pkg"
        elif has_c and not languages - {"c"}:
            kind = "firmware"
        else:
            kind = "generic"

        components.append(
            Component(
                name=dirname,
                kind=kind,
                root_relpath=rel_dir,
                languages=sorted(languages),
                test_paths=sorted(test_paths),
                doc_paths=sorted(doc_paths),
            )
        )

    return components


# ---------------------------------------------------------------------------
# Dependency detection
# ---------------------------------------------------------------------------


_PY_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([a-zA-Z_][\w\.]*)\s+import|import\s+([a-zA-Z_][\w\.]*))"
)


def _parse_python_imports(text: str) -> Set[str]:
    """
    Parse top-level import statements in a Python file.
    Returns a set of top-level module/package names.
    """
    names: Set[str] = set()
    for line in text.splitlines():
        m = _PY_IMPORT_RE.match(line)
        if not m:
            continue
        pkg = m.group(1) or m.group(2)
        if not pkg:
            continue
        top = pkg.split(".")[0]
        names.add(top)
    return names


def _index_component_python_imports(
    root_path: str,
    component: Component,
) -> Dict[str, Set[str]]:
    """
    Map from absolute file path -> set(imported_top_level_names).
    """
    root_abs = _normalize_root(root_path)
    comp_root_abs = os.path.join(root_abs, component.root_relpath)
    index: Dict[str, Set[str]] = {}

    for dirpath, dirnames, filenames in os.walk(comp_root_abs):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            imports = _parse_python_imports(text)
            if imports:
                index[os.path.relpath(full, root_abs).replace("\\", "/")] = imports

    return index


def _build_dependency_edges(
    root_path: str,
    components: List[Component],
) -> List[DependencyEdge]:
    """
    Build a list of internal dependency edges between components.

    Currently supports:
    - Python imports between top-level components.
    """
    name_to_component = {c.name: c for c in components}
    # Allow mapping from top-level package name (e.g. 'aetherone') to component.
    # We use the directory name as the package name assumption.
    pkg_to_component: Dict[str, str] = {}
    for c in components:
        pkg_to_component[c.name] = c.name

    edges: List[DependencyEdge] = []
    seen_edges: Set[Tuple[str, str, str]] = set()
    root_abs = _normalize_root(root_path)

    for comp in components:
        if "python" not in comp.languages:
            continue

        import_index = _index_component_python_imports(root_abs, comp)

        for relpath, imports in import_index.items():
            for top in imports:
                if top in pkg_to_component and pkg_to_component[top] != comp.name:
                    target_comp = pkg_to_component[top]
                    reason = f"python_import:{top}"
                    key = (comp.name, target_comp, reason)
                    if key in seen_edges:
                        continue
                    seen_edges.add(key)
                    edges.append(
                        DependencyEdge(
                            from_component=comp.name,
                            to_component=target_comp,
                            reason=reason,
                        )
                    )

    return edges


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_monorepo_model(root_path: str) -> MonorepoModel:
    """
    Build a MonorepoModel for the given root path.

    Intended to be called by agents that need a high-level map of the repo.
    """
    root_abs = _normalize_root(root_path)
    components = _detect_top_level_components(root_abs)
    dependencies = _build_dependency_edges(root_abs, components)
    return MonorepoModel(
        root_path=root_abs,
        components=components,
        dependencies=dependencies,
    )


def _build_component_index(
    model: MonorepoModel,
) -> Tuple[Dict[str, Component], Dict[str, str]]:
    """
    Build:
        - name -> Component
        - file (relpath) -> owning component name
    """
    name_to_comp = {c.name: c for c in model.components}
    file_to_component: Dict[str, str] = {}
    root = model.root_path

    for comp in model.components:
        comp_root_abs = os.path.join(root, comp.root_relpath)
        for dirpath, dirnames, filenames in os.walk(comp_root_abs):
            dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root).replace("\\", "/")
                file_to_component[rel] = comp.name

    return name_to_comp, file_to_component


def _resolve_transitive_dependents(
    model: MonorepoModel,
    base_components: Set[str],
) -> Set[str]:
    """
    Given a set of base components, return all components that depend
    directly or indirectly on them (reverse graph traversal).
    """
    # Build reverse adjacency: who depends on whom
    dependents: Dict[str, Set[str]] = {}
    for edge in model.dependencies:
        dependents.setdefault(edge.to_component, set()).add(edge.from_component)

    result: Set[str] = set()
    frontier: List[str] = list(base_components)

    while frontier:
        current = frontier.pop()
        for dep in dependents.get(current, set()):
            if dep not in result and dep not in base_components:
                result.add(dep)
                frontier.append(dep)

    return result


def plan_change_impact(
    model: MonorepoModel,
    changed_paths: Iterable[str],
) -> ChangeImpactPlan:
    """
    Compute a change impact plan for a set of changed file paths.

    changed_paths:
        Iterable of file paths relative to the repo root, or absolute paths
        (absolute paths will be normalised and converted to relpaths).
    """
    root = model.root_path
    _, file_to_component = _build_component_index(model)

    normalized_changes: List[str] = []
    touched_components: Set[str] = set()

    for p in changed_paths:
        if not p:
            continue
        if os.path.isabs(p):
            rel = os.path.relpath(p, root)
        else:
            rel = p
        rel_norm = rel.replace("\\", "/")
        normalized_changes.append(rel_norm)
        owner = file_to_component.get(rel_norm)
        if owner:
            touched_components.add(owner)

    transitive = _resolve_transitive_dependents(model, touched_components)

    # Recommended tests:
    #   - All tests under touched components
    #   - All tests under transitive dependents
    test_paths: Set[str] = set()
    for comp in model.components:
        if comp.name in touched_components or comp.name in transitive:
            for t in comp.test_paths:
                test_paths.add(t)

    return ChangeImpactPlan(
        changed_files=normalized_changes,
        touched_components=sorted(touched_components),
        directly_impacted_components=sorted(touched_components),
        transitively_impacted_components=sorted(transitive),
        recommended_test_paths=sorted(test_paths),
    )

