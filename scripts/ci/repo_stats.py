#!/usr/bin/env python3
"""The repository numbers quoted in SALE_READINESS.md and the due-diligence document (KAN-182).

  python scripts/ci/repo_stats.py            print the numbers
  python scripts/ci/repo_stats.py --write    also collect the tests and rewrite the generated table in both documents
  python scripts/ci/repo_stats.py --check    exit 1 when a document's table has drifted from the repository

The table in the documents sits between the repo_stats:begin / repo_stats:end markers and is written
only by --write, so no figure in it is typed by hand. --check (also run by scripts/ci/check_docs.py and
tests/test_docs_match_code.py) recomputes every row except the two it cannot: the commit count (CI may
use a shallow clone, and committing the table changes it) and the collected-test count (needs a pytest
collection; the `def test_` row stands in for it).
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ["SALE_READINESS.md", "AETHEROS_ACQUISITION_DUE_DILIGENCE.md"]
BEGIN, END = "<!-- repo_stats:begin", "<!-- repo_stats:end -->"
NOT_RECHECKED = {"Git commits", "Tests collected by pytest"}
# ponytail: a row may be up to 5% off before --check fails. An exact match would fail on every commit that
# adds a Python line; 5% still catches a table carried over from an old branch. Tighten if releases need it.
TOLERANCE = 0.05


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def _count_lines(path):
    with open(ROOT / path, errors="ignore") as fh:
        return sum(1 for _ in fh)


def stats(collect=False):
    """{metric: (value, how it is counted)} in table order. All counts are over git-tracked files."""
    py = [f for f in git("ls-files", "*.py").split() if (ROOT / f).exists()]
    lines = {f: _count_lines(f) for f in py}
    routers = [f for f in py if re.fullmatch(r"gateway/routers/[^/]+\.py", f)]
    tests = [f for f in py if f.startswith("tests/")]
    text = {f: (ROOT / f).read_text(errors="ignore") for f in routers + tests}
    over = sorted((f, n) for f, n in lines.items() if n > 600)
    bare = sorted(f"{f}:{i}" for f in py for i, t in enumerate((ROOT / f).read_text(errors="ignore").splitlines(), 1)
                  if re.match(r"\s*except\s*:", t))
    tracked = git("ls-files").split()
    out = {
        "Git commits": (int(git("rev-list", "--count", "HEAD")), "`git rev-list --count HEAD`"),
        "Tracked Python files": (len(py), "`git ls-files '*.py'`"),
        "Python lines (tracked files)": (sum(lines.values()), "lines of those files"),
        "Alembic migration files": (sum(bool(re.fullmatch(r"alembic/versions/[^/]+\.py", f)) for f in py),
                                    "`alembic/versions/*.py`"),
        "Gateway router files named `*_router.py`": (sum(f.endswith("_router.py") for f in routers),
                                                     "`gateway/routers/*_router.py`"),
        "All `.py` files in `gateway/routers/`": (len(routers), "`gateway/routers/*.py`"),
        "Route decorators in `gateway/routers/*.py`": (
            sum(len(re.findall(r"(?m)^\s*@\w*router\.(?:get|post|put|patch|delete|websocket|api_route)\(", text[f]))
                for f in routers), "lines starting `@...router.<method>(`"),
        "Pipeline stages": (len({f.split("/")[1] for f in py if re.match(r"stages/s\d", f)}), "`stages/s<digit>*/`"),
        "Phase directories": (len({f.split("/")[1] for f in py if re.match(r"phases/p\d", f)}), "`phases/p<digit>*/` (`phases/patterns/` is not a phase)"),
        "Tracked Python files under `phases/`": (sum(f.startswith("phases/") for f in py), "`git ls-files 'phases/*.py'`"),
        "Test files": (sum(bool(re.search(r"test_.*\.py$", f)) for f in tests), "`tests/**/test_*.py`"),
        "`def test_` lines in `tests/`": (
            sum(len(re.findall(r"(?m)^\s*(?:async )?def test_", text[f])) for f in tests),
            "lower than the collected count: parametrized tests expand"),
        "Frontend source files in `dashboard/src`": (
            sum(bool(re.match(r"dashboard/src/.*\.(tsx|jsx|ts|js)$", f)) for f in tracked), "`.ts .tsx .js .jsx`"),
        "Benchmark prompt files": (sum(bool(re.fullmatch(r"benchmarks/prompts/[^/]+", f)) for f in tracked),
                                   "`benchmarks/prompts/*`"),
        "Python files over 600 lines": (len(over), ", ".join(f"`{f}` {n}" for f, n in over) or "none"),
        "`dashboard/src/pages/ProjectView.jsx` lines": (_count_lines("dashboard/src/pages/ProjectView.jsx"), "`wc -l`"),
        "Bare `except:` lines": (len(bare), ", ".join(f"`{b}`" for b in bare) or "none"),
    }
    if collect:
        done = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
                              cwd=ROOT, capture_output=True, text=True)
        m = re.search(r"(\d+) tests? collected", done.stdout)
        if not m or " error" in done.stdout.splitlines()[-1]:
            raise SystemExit(f"pytest collection failed:\n{done.stdout[-800:]}\n{done.stderr[-800:]}")
        out["Tests collected by pytest"] = (int(m.group(1)), "`python -m pytest --collect-only -q tests` (collection only, not a run)")
    return out


def render(st):
    head = git("log", "-1", "--format=%h %cs").split()
    rows = "\n".join(f"| {k} | {v} | {how} |" for k, (v, how) in st.items())
    return (f"{BEGIN} (written by `python scripts/ci/repo_stats.py --write`; do not edit by hand) -->\n"
            f"Computed by `python scripts/ci/repo_stats.py --write` on the working tree on top of commit `{head[0]}` "
            f"({head[1]}). Counts are over git-tracked files.\n\n"
            f"| Metric | Value | How it is counted |\n|---|---|---|\n{rows}\n{END}")


def _block(doc):
    text = (ROOT / doc).read_text()
    a, b = text.find(BEGIN), text.find(END)
    return (text, a, b + len(END)) if 0 <= a < b else (text, -1, -1)


def write():
    block = render(stats(collect=True))
    for doc in DOCS:
        text, a, b = _block(doc)
        if a < 0:
            raise SystemExit(f"{doc}: no {BEGIN} ... {END} markers to write between")
        (ROOT / doc).write_text(text[:a] + block + text[b:])
        print(f"wrote {doc}")


def drift(docs=DOCS, now=None):
    """Problems (`file: message`) where a document's generated table no longer matches the repository."""
    now = now or stats()
    out = []
    for doc in docs:
        text, a, b = _block(doc)
        if a < 0:
            out.append(f"{doc}: no generated repo_stats table (run python scripts/ci/repo_stats.py --write)")
            continue
        quoted = {m[1].strip(): int(m[2]) for m in re.finditer(r"(?m)^\| (.+?) \| (\d+) \|", text[a:b])}
        for metric, (value, _) in now.items():
            if metric in NOT_RECHECKED:
                continue
            if metric not in quoted:
                out.append(f"{doc}: the table has no row '{metric}' (run python scripts/ci/repo_stats.py --write)")
            elif abs(quoted[metric] - value) > TOLERANCE * value:
                out.append(f"{doc}: '{metric}' says {quoted[metric]}, the repository has {value} "
                           f"(run python scripts/ci/repo_stats.py --write)")
    return out


def main(argv):
    if "--check" in argv:
        problems = drift()
        print("\n".join(problems) or "repo_stats: the documents match the repository")
        return 1 if problems else 0
    if "--write" in argv:
        write()
        return 0
    for k, (v, how) in stats().items():
        print(f"{k}: {v}  ({how})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
