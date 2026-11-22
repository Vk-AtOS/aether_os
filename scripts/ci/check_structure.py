#!/usr/bin/env python3
"""Structure gate (VEL-37): import cycles, silent excepts and oversized files, with a ratcheting baseline.

Checks every non-test Python file in the checkout (the checkout root is the `aether_os` package):
  - cycle:   a module-level import cycle between top-level packages/modules (function-level imports are the
             sanctioned way to break a cycle and are ignored).
  - silent:  `except:` (bare), or `except ...:` whose body is only `pass`/`...` (nothing logged or re-raised).
  - size:    a file over 600 lines.

scripts/ci/structure_baseline.json lists violations that already existed. A violation not in the baseline
fails; a baseline entry that no longer occurs also fails (the baseline may only shrink: delete the entry).
Keys carry no line numbers for silent excepts (file + enclosing function + occurrence), so edits elsewhere do not churn them.

  python scripts/ci/check_structure.py                  check
  python scripts/ci/check_structure.py --write-baseline regenerate the baseline (review the diff: it must only shrink)
"""
import argparse
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).with_name("structure_baseline.json")
MAX_LINES = 600
SKIP_DIRS = {".git", "__pycache__", "node_modules", "tests", "venv", ".venv"}


def iter_files(root: Path):
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if SKIP_DIRS & set(rel.parts[:-1]) or rel.name.startswith("test_") or rel.name == "conftest.py":
            continue
        yield p, rel


def _is_silent(h: ast.ExceptHandler) -> bool:
    if h.type is None:
        return True
    return all(isinstance(b, ast.Pass) or (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant)
                                           and b.value.value is Ellipsis) for b in h.body)


def silent_excepts(tree: ast.AST, rel: str) -> list[str]:
    out: list[str] = []
    counts: dict[str, int] = defaultdict(int)

    def walk(node, scope):
        for child in ast.iter_child_nodes(node):
            sc = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                sc = f"{scope}.{child.name}" if scope else child.name
            if isinstance(child, ast.ExceptHandler) and _is_silent(child):
                kind = "bare except" if child.type is None else "except-pass"
                key = f"{rel}::{scope or '<module>'}::{kind}"
                counts[key] += 1
                out.append(f"{key}#{counts[key]}")
            walk(child, sc)

    walk(tree, "")
    return out


def top_module(rel: Path) -> str:
    return rel.parts[0] if len(rel.parts) > 1 else rel.stem


def import_edges(tree: ast.Module, rel: Path, tops: set[str]) -> set[str]:
    """Top-level (module-body, incl. if/try blocks) imports of other first-party top-level modules."""
    me, deps = top_module(rel), set()

    def visit(stmts):
        for n in stmts:
            names = []
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and not n.level:
                names = [n.module or ""]
                if n.module == "aether_os":
                    names = [a.name for a in n.names]
                    names = [f"aether_os.{x}" for x in names]
            elif isinstance(n, ast.ImportFrom) and n.level:
                # relative: level 1 inside a package stays in that package; level 2+ climbs to a sibling top-level
                pkg_depth = len(rel.parts) - 1
                if n.level > pkg_depth and n.module:
                    names = [f"aether_os.{n.module}"]
            for name in names:
                parts = name.split(".")
                if parts[0] == "aether_os" and len(parts) > 1:
                    parts = parts[1:]
                elif parts[0] == "aether_os":
                    continue
                if parts[0] in tops and parts[0] != me:
                    deps.add(parts[0])
            for field in ("body", "orelse", "finalbody"):
                if isinstance(n, (ast.If, ast.Try)):
                    visit(getattr(n, field, []))
            if isinstance(n, ast.Try):
                for h in n.handlers:
                    visit(h.body)

    visit(tree.body)
    return deps


def find_cycles(graph: dict[str, set[str]]) -> list[str]:
    """One entry per strongly connected component of size > 1 (Tarjan)."""
    index, low, on, stack, comps, counter = {}, {}, set(), [], [], [0]

    def strong(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in sorted(graph.get(v, ())):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                comps.append(sorted(comp))

    sys.setrecursionlimit(10000)
    for v in sorted(graph):
        if v not in index:
            strong(v)
    return [f"cycle::{' <-> '.join(c)}" for c in sorted(comps)]


def collect(root: Path = ROOT) -> list[str]:
    found: list[str] = []
    parsed, tops = [], set()
    for p, rel in iter_files(root):
        tops.add(top_module(rel))
        text = p.read_text(encoding="utf-8", errors="replace")
        n = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        if n > MAX_LINES:
            found.append(f"size::{rel.as_posix()}")
        try:
            parsed.append((rel, ast.parse(text)))
        except SyntaxError:
            found.append(f"syntax::{rel.as_posix()}")
    graph: dict[str, set[str]] = defaultdict(set)
    for rel, tree in parsed:
        found += silent_excepts(tree, rel.as_posix())
        graph[top_module(rel)] |= import_edges(tree, rel, tops)
    found += find_cycles(graph)
    return sorted(found)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    found = collect(Path(args.root))
    if args.write_baseline:
        BASELINE.write_text(json.dumps(found, indent=1) + "\n")
        print(f"baseline written: {len(found)} entries")
        return 0
    base = set(json.loads(BASELINE.read_text())) if BASELINE.exists() else set()
    new, gone = sorted(set(found) - base), sorted(base - set(found))
    for v in new:
        print(f"FAIL new violation: {v}")
    for v in gone:
        print(f"FAIL stale baseline entry (fixed, remove it from {BASELINE.name}): {v}")
    print(f"{len(found)} known violation(s), {len(new)} new, {len(gone)} stale")
    return 1 if new or gone else 0


if __name__ == "__main__":
    sys.exit(main())
