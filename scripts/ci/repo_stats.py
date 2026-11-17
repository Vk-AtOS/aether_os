#!/usr/bin/env python3
"""Print the repository numbers quoted in SALE_READINESS.md and the due-diligence document (KAN-182).

Same commands as the tables, so a reader can reproduce each figure: python scripts/ci/repo_stats.py
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout


py = git("ls-files", "*.py").split()
lines = {f: sum(1 for _ in open(ROOT / f, errors="ignore")) for f in py if (ROOT / f).exists()}
print("Commits", git("rev-list", "--count", "HEAD").strip())
print("Tracked Python files", len(py))
print("Python lines", sum(lines.values()))
print("Tracked Python files under phases/", sum(f.startswith("phases/") for f in py))
print("Test files", sum(bool(re.search(r"test_.*\.py$", f)) for f in git("ls-files", "tests").split()))
print("Frontend source files (dashboard/src)", sum(bool(re.search(r"\.(tsx|jsx|ts|js)$", f)) for f in git("ls-files", "dashboard/src").split()))
print("Python files over 600 lines", sorted((n, f) for f, n in lines.items() if n > 600))
