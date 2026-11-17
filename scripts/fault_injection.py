#!/usr/bin/env python3.11
"""Fault injection (KAN-52): stop each service of the compose stack in turn, probe what still works, compare with the design.

    python3.11 scripts/fault_injection.py --table                      # print the design table (docs/ops/BLAST_RADIUS.md)
    python3.11 scripts/fault_injection.py --run --token "$TOKEN" \
        [--compose-file docker-compose.yml] [--api http://127.0.0.1:8000] [--preview http://127.0.0.1:8100]

--run needs Docker, a running stack (`docker compose up -d`, add `--profile velaris` for the Velaris rows) and a user token for the
authenticated probes. Without Docker or a reachable stack it prints SKIP and exits 0 (the in-process version of the same
design table runs in tests/test_blast_radius.py). Every service is restarted afterwards, also on failure or Ctrl-C.
Exit 0 = every row matches the design (or skipped), 1 = a gap: each gap line is a ticket to open.

DESIGN says what must still work when one thing is down. "up" = HTTP 200, "refused" = 503 by design (fails closed),
"down" = no answer at all. Probes: /healthz (process alive), /readyz (can serve), /auth/my-orgs (authenticated read: needs
Postgres + Redis), /velaris/agents (Velaris through the gateway), preview /__preview/health.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

PROBES = ["healthz", "readyz", "authed read", "velaris", "preview"]

# stopped service -> expected state of each probe. Redis: the token revocation check fails closed, so authenticated calls are
# refused (503) while Redis is down; Velaris and previews are optional and must not take the API down with them.
DESIGN: Dict[str, Dict[str, str]] = {
    "(nothing)": {"healthz": "up", "readyz": "up", "authed read": "up", "velaris": "up", "preview": "up"},
    "db": {"healthz": "up", "readyz": "refused", "authed read": "refused", "velaris": "refused", "preview": "up"},
    "redis": {"healthz": "up", "readyz": "refused", "authed read": "refused", "velaris": "refused", "preview": "up"},
    "velaris": {"healthz": "up", "readyz": "up", "authed read": "up", "velaris": "refused", "preview": "up"},
    "preview": {"healthz": "up", "readyz": "up", "authed read": "up", "velaris": "up", "preview": "down"},
    "api": {"healthz": "down", "readyz": "down", "authed read": "down", "velaris": "down", "preview": "up"},
}
# Compose service names; velaris needs `--profile velaris`.
SERVICE = {"db": "db", "redis": "redis", "velaris": "velaris", "preview": "preview", "api": "api"}


def table() -> str:
    head = "| stopped | " + " | ".join(PROBES) + " |\n|---|" + "---|" * len(PROBES) + "\n"
    return head + "".join(f"| {k} | " + " | ".join(v[p] for p in PROBES) + " |\n" for k, v in DESIGN.items())


def probe(url: str, token: Optional[str] = None, timeout: float = 5.0) -> str:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return "up" if r.status == 200 else f"http {r.status}"
    except urllib.error.HTTPError as e:
        return "refused" if e.code in (502, 503, 504) else f"http {e.code}"
    except (urllib.error.URLError, OSError, TimeoutError):
        return "down"


def probe_all(api: str, preview: str, token: str) -> Dict[str, str]:
    return {"healthz": probe(f"{api}/healthz"), "readyz": probe(f"{api}/readyz"),
            "authed read": probe(f"{api}/auth/my-orgs", token), "velaris": probe(f"{api}/velaris/agents", token),
            "preview": probe(f"{preview}/__preview/health")}


def compose(args: List[str], file: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", "-f", file, *args], capture_output=True, text=True, timeout=timeout)


def compare(stopped: str, actual: Dict[str, str]) -> List[str]:
    return [f"stopping {stopped}: {p} is '{actual[p]}', design says '{want}'"
            for p, want in DESIGN[stopped].items() if actual.get(p) != want]


def run(api: str, preview: str, token: str, file: str, settle: float = 12.0) -> int:
    if not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        print("SKIP: Docker is not available (the in-process version runs in tests/test_blast_radius.py)")
        return 0
    base = probe_all(api, preview, token)
    if base["healthz"] != "up":
        print(f"SKIP: the stack is not reachable at {api} (start it with docker compose up -d)")
        return 0
    gaps: List[str] = compare("(nothing)", base)
    rows = {"(nothing)": base}
    for name in ("db", "redis", "velaris", "preview", "api"):
        svc = SERVICE[name]
        if compose(["ps", "-q", svc], file).stdout.strip() == "":
            print(f"skip {name}: service not running in this stack")
            continue
        try:
            compose(["stop", svc], file)
            time.sleep(settle)
            rows[name] = probe_all(api, preview, token)
            gaps += compare(name, rows[name])
        finally:
            compose(["start", svc], file)
            time.sleep(settle)
    print("| stopped | " + " | ".join(PROBES) + " |\n|---|" + "---|" * len(PROBES))
    for k, v in rows.items():
        print(f"| {k} | " + " | ".join(v[p] for p in PROBES) + " |")
    for g in gaps:
        print("GAP:", g)
    print(json.dumps({"rows": rows, "gaps": gaps}))
    return 1 if gaps else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--preview", default="http://127.0.0.1:8100")
    ap.add_argument("--token", default="")
    ap.add_argument("--compose-file", default="docker-compose.yml")
    args = ap.parse_args(argv)
    if args.table:
        print(table(), end="")
        return 0
    if args.run:
        if not args.token:
            print("--token is required for the authenticated probes", file=sys.stderr)
            return 2
        return run(args.api, args.preview, args.token, args.compose_file)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
