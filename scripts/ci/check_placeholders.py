#!/usr/bin/env python3
"""Refuse to deploy manifests that still carry template placeholders (KAN-197).

Usage: check_placeholders.py [DIR]   (default deploy/kubernetes)
Exit 1 and list file:line for every REPLACE_ME / yourdomain.com / TODO: replace left in DIR.
deploy/kubernetes/apply.sh runs this before `kubectl apply`.
"""
import pathlib
import re
import sys

PATTERN = re.compile(r"REPLACE_ME|yourdomain\.com|TODO:? *replace", re.IGNORECASE)


def find_placeholders(root: pathlib.Path) -> list:
    hits = []
    for f in sorted(root.rglob("*.y*ml")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if PATTERN.search(line):
                hits.append(f"{f}:{n}")
    return hits


def main(argv: list) -> int:
    root = pathlib.Path(argv[1] if len(argv) > 1 else "deploy/kubernetes")
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    hits = find_placeholders(root)
    for h in hits:
        print(f"placeholder left: {h}", file=sys.stderr)
    if hits:
        print(f"{len(hits)} placeholder(s): fill them in a private copy of the manifests, then deploy that copy.",
              file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
