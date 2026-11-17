#!/usr/bin/env python3
"""Fail when README/API_REFERENCE/RUNBOOK/ARCHITECTURE/SECURITY name something the code does not have (KAN-181).

Checks (each finding prints `file:line: message`, exit 1 if any):
  routes   every `| METHOD | `/path` |` row of API_REFERENCE.md and every inline `METHOD /path` exists in the
           live FastAPI app; every app route is listed in API_REFERENCE.md; no row has an empty summary.
  paths    every backticked repo path (has a known extension or ends in /) exists.
  env      every backticked UPPER_SNAKE name with an underscore appears in some non-doc source file.
  commands every `bash|python|python3 <script>` and `python -m aether_os.x` in the docs names an existing file.

Run from anywhere with the checkout importable as `aether_os` (PYTHONPATH=<parent dir>). `--no-routes` skips the import.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ["README.md", "API_REFERENCE.md", "RUNBOOK.md", "ARCHITECTURE.md", "SECURITY.md"]
EXT = r"py|sh|md|ya?ml|json|toml|ini|txt|conf|cfg|jsonl|lock|sql|tpl|j2|html|ts|tsx|js|env\.example"
SRC_EXT = {".py", ".sh", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".json", ".ts", ".tsx", ".js", ".tpl", ".j2", ".env", ".example"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build", ".pytest_cache", ".ruff_cache"}
# Tokens that look like env vars but are conventions, not configuration of this code base.
ENV_IGNORE = {"UPPER_SNAKE", "ACCESS_TOKEN", "REFRESH_TOKEN", "SSE_TOKEN", "MFA_TOKEN"}
# Things that exist only on a deployed host or are produced by running something (not in the repo).
PATH_IGNORE_PREFIX = ("/etc/", "/var/", "/opt/", "/usr/", "/tmp/", "/root/", "/home/", "/data/", "/app/", "/proc/", "/dev/", "~/", "http")
HEADING_SKIP = re.compile(r"^```")


NEGATED = re.compile(r"\b(no|not|never|nowhere|without|none|nothing)\b|n't", re.I)  # "there is no X" is a true statement


def lines(doc):
    """Yield (lineno, text, in_fence) for a doc."""
    fence = False
    for i, t in enumerate((ROOT / doc).read_text().splitlines(), 1):
        if t.lstrip().startswith("```"):
            fence = not fence
            continue
        yield i, t, fence


def source_text():
    chunks = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            p = Path(dp) / f
            if p.suffix in SRC_EXT or f.startswith(".env") or f in ("Dockerfile", "Makefile") or "docker-compose" in f:
                if p.name in DOCS or "confluence_corrections" in p.name or p.name == "check_docs.py":
                    continue
                try:
                    chunks.append(p.read_text(errors="ignore"))
                except OSError:
                    continue
    return "\n".join(chunks)


def check_routes(out):
    from fastapi.routing import APIRoute

    from aether_os.gateway.api import app

    live = {}
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                live[(m, r.path)] = r
    row = re.compile(r"^\| (GET|POST|PUT|PATCH|DELETE) \| `([^`]+)` \| (.*) \|$")
    seen = set()
    for i, t, fence in lines("API_REFERENCE.md"):
        m = row.match(t)
        if not m:
            continue
        key = (m.group(1), m.group(2))
        seen.add(key)
        if key not in live:
            out.append(f"API_REFERENCE.md:{i}: route {key[0]} {key[1]} is not in the app")
        summary = m.group(3).rsplit(" | ", 1)[-1].strip()
        if summary in ("", "(no docstring)", "-"):
            out.append(f"API_REFERENCE.md:{i}: empty summary for {key[0]} {key[1]}")
    for key in sorted(set(live) - seen):
        out.append(f"API_REFERENCE.md: route {key[0]} {key[1]} is in the app but not listed")
    inline = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`\s?]*)")
    norm = lambda p: re.sub(r"\{[^}]*\}", "{}", p)  # {id} and {run_id} are the same route
    live_norm = {(m, norm(p)) for m, p in live}
    for doc in DOCS:
        if doc == "API_REFERENCE.md":
            continue
        for i, t, _ in lines(doc):
            if NEGATED.search(t):
                continue
            for m in inline.finditer(t):
                if (m.group(1), norm(m.group(2))) not in live_norm:
                    out.append(f"{doc}:{i}: route {m.group(1)} {m.group(2)} is not in the app")


def check_paths_env_cmds(out, docs=None, src=None):
    docs = docs or DOCS
    src = source_text() if src is None else src
    tick = re.compile(r"`([^`\n]+)`")
    pathre = re.compile(rf"^[\w./@-]+(\.({EXT})|/)$")
    envre = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$")
    cmdre = re.compile(r"(?:^|[\s;&|$(])(?:sudo\s+)?(?:bash|sh|python3?(?:\.\d+)?)\s+(?:-[a-zA-Z]+\s+)*([\w./-]+\.(?:py|sh))")
    modre = re.compile(r"python3?(?:\.\d+)?\s+-m\s+([\w.]+)")
    for doc in docs:
        for i, t, fence in lines(doc):
            if NEGATED.search(t) and not fence:
                continue
            toks = [t] if fence else [m.group(1) for m in tick.finditer(t)]
            for tok in toks:
                s = tok.strip()
                if not fence:
                    if envre.match(s) and s not in ENV_IGNORE and s not in src:
                        out.append(f"{doc}:{i}: env var {s} is not used anywhere in the code")
                    p = s.split("::")[0].split(":")[0].rstrip(",.")
                    if pathre.match(p) and "/" in p and not p.startswith(PATH_IGNORE_PREFIX) and not p.startswith("/") and "*" not in p and "<" not in p:
                        base = p.removeprefix("./")
                        if not ((ROOT / base).exists() or (ROOT.parent / base).exists()):
                            out.append(f"{doc}:{i}: path {p} does not exist")
                for m in cmdre.finditer(s):
                    f = m.group(1)
                    if not f.startswith(("/", "~", "$")) and not (ROOT / f.removeprefix("./")).exists() and not (ROOT.parent / f).exists():
                        out.append(f"{doc}:{i}: command refers to missing script {f}")
                for m in modre.finditer(s):
                    mod = m.group(1)
                    parts = mod.split(".")
                    if parts[0] == "aether_os":
                        parts = parts[1:]
                    rel = ROOT.joinpath(*parts)
                    if parts and not (rel.with_suffix(".py").exists() or (rel / "__init__.py").exists() or (rel / "__main__.py").exists()) and (ROOT / parts[0] / "__init__.py").exists():
                        out.append(f"{doc}:{i}: python -m {mod} does not exist")


def main():
    out = []
    if "--no-routes" not in sys.argv:
        check_routes(out)
    check_paths_env_cmds(out)
    for o in out:
        print(o)
    print(f"check_docs: {len(out)} problem(s)")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
