"""Targeted gate retry helpers (KAN-210): name the failing files, never repeat an identical failure.

Production run 12 (22 Nov 2026): s04 re-ran its whole stage three times (712 s) on the same broken `TaskPage.tsx`
line, because the gate said only "sub-step reported failure" and the retry fed the stage the same input again.
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, Iterable, List, Mapping

# tsc: "src/pages/X.tsx(254,306): error TS1005: ..."; vite/esbuild: "/abs/.../src/pages/X.tsx:291:42: ERROR: ..."
_LOC_RE = re.compile(r"((?:[\w@.-]+/)*[\w@.-]+\.(?:tsx|ts|jsx|js|css|py))(?:\(\d+,\d+\)|:\d+(?::\d+)?)")
_MAX_LINES_PER_FILE = 3
_MAX_LINE_CHARS = 300


def parse_failed_files(output: str) -> Dict[str, str]:
    """{file path: first error lines} from tsc / vite / compiler output. Paths are cut to start at `src/` when present."""
    found: Dict[str, List[str]] = {}
    for line in (output or "").splitlines():
        m = _LOC_RE.search(line)
        if not m:
            continue
        path = m.group(1)
        path = path[path.index("src/"):] if "src/" in path else path
        if "node_modules" in path:
            continue
        lines = found.setdefault(path, [])
        if len(lines) < _MAX_LINES_PER_FILE:
            lines.append(line.strip()[:_MAX_LINE_CHARS])
    return {p: " | ".join(ls) for p, ls in found.items()}


def failure_signature(failed_files: Mapping[str, str], issues: Iterable[str] = ()) -> str:
    """Hash of (file set + error text). The same signature twice means the last attempt changed nothing."""
    parts = sorted(f"{p}\x00{e}" for p, e in failed_files.items()) or sorted(str(i) for i in issues)
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def describe_failures(failed_files: Mapping[str, str], limit: int = 5) -> str:
    """'path: error; path: error' for escalation messages and gate issues."""
    items = [f"{p}: {e}" for p, e in list(failed_files.items())[:limit]]
    extra = len(failed_files) - limit
    return "; ".join(items) + (f"; and {extra} more file(s)" if extra > 0 else "")
