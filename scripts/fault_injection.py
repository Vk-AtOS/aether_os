#!/usr/bin/env python3.11
"""Fault injection (KAN-52): break each service of the compose stack in turn, probe what still works, compare with the design.

    python3.11 scripts/fault_injection.py --table                      # print the design table (docs/ops/BLAST_RADIUS.md)
    python3.11 scripts/fault_injection.py --run --token "$TOKEN" \
        [--compose-file docker-compose.yml] [--api http://127.0.0.1:8000] [--preview http://127.0.0.1:8100] \
        [--faults stop,slow,partition] [--disk-full /var/lib/docker/aether-fill]

Faults: "stop" stops the service; "slow" adds SLOW_MS of delay to every packet it sends (tc netem, run from a helper container in
the service's network namespace, so the service image needs nothing); "partition" disconnects it from the compose network
(packets vanish: callers see timeouts, not refusals); --disk-full fills the filesystem holding PATH (root, same filesystem as
the Docker data root) to a few MB free, probes, then deletes the file. "dropped" = the connection closed without a response. A probe that takes longer than PROBE_TIMEOUT is "hang":
the design never allows a hang, because a request stuck on a dead dependency holds a worker.

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
import http.client
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional

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
# A partitioned dependency must fail closed inside the client timeouts (core/db.py, Redis socket_timeout 5 s, Velaris breaker),
# never hang: the same row as stopped.
for _svc in ("db", "redis", "velaris"):
    DESIGN[f"partition {_svc}"] = dict(DESIGN[_svc])
# Slow (SLOW_MS per packet) but inside each caller's budget: the work still gets done, more slowly. Exceptions: /readyz
# checks with short timeouts, so a slow dependency takes the instance out of rotation; a new PostgreSQL connection needs
# several round trips (TCP, startup, SCRAM) and does not fit DB_CONNECT_TIMEOUT_S, so requests fail closed like a stopped
# database (observed on the AWS testbed, 21 Nov 2026).
DESIGN["slow db"] = dict(DESIGN["db"])
DESIGN["slow redis"] = {**DESIGN["(nothing)"], "readyz": "refused"}
DESIGN["slow velaris"] = dict(DESIGN["(nothing)"])
# A full disk stops writes; reads, health and previews keep working.
DESIGN["disk full"] = dict(DESIGN["(nothing)"])
# No model provider usable (documented, not injected: providers are external). Verified by tests/test_model_admission.py (runs
# are refused with 503) and by the 21 Nov AWS testbed runs that had no model key.
DESIGN["no model"] = {"healthz": "up", "readyz": "up", "authed read": "up", "velaris": "up", "preview": "up"}
SLOW_MS = 3000
PROBE_TIMEOUT = 40.0   # past the API's own budget (statement timeout 30 s + 5 s client margin, core/db.py)
NETEM_IMAGE = "aether-netem:1"
# Compose service names; velaris needs `--profile velaris`.
SERVICE = {"db": "db", "redis": "redis", "velaris": "velaris", "preview": "preview", "api": "api"}


def table() -> str:
    head = "| stopped | " + " | ".join(PROBES) + " |\n|---|" + "---|" * len(PROBES) + "\n"
    return head + "".join(f"| {k} | " + " | ".join(v[p] for p in PROBES) + " |\n" for k, v in DESIGN.items())


def probe(url: str, token: Optional[str] = None, timeout: float = PROBE_TIMEOUT) -> str:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return "up" if r.status == 200 else f"http {r.status}"
    except urllib.error.HTTPError as e:
        return "refused" if e.code in (502, 503, 504) else f"http {e.code}"
    except TimeoutError:
        return "hang"
    except urllib.error.URLError as e:
        return "hang" if isinstance(e.reason, TimeoutError) else "down"
    except http.client.RemoteDisconnected:
        return "dropped"      # the server accepted the request and closed the connection without an answer
    except OSError:
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


def container_of(svc: str, file: str) -> str:
    return compose(["ps", "-q", svc], file).stdout.strip()


def docker(args: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def netem(cid: str, on: bool) -> None:
    """Add or remove SLOW_MS delay on the container's network interface, from a helper sharing its network namespace."""
    if docker(["image", "inspect", NETEM_IMAGE]).returncode != 0:
        subprocess.run(["docker", "build", "-q", "-t", NETEM_IMAGE, "-"], input="FROM alpine:3.20\nRUN apk add --no-cache iproute2\n",
                       text=True, capture_output=True, check=True)
    # replace, not add: a delay left behind by an interrupted run must not make the next run fail. The interface is looked
    # up, not assumed: after a partition (disconnect + connect) the container's interface is eth1, not eth0.
    tc = f"tc qdisc replace dev $DEV root netem delay {SLOW_MS}ms" if on else "tc qdisc del dev $DEV root"
    script = "DEV=$(ip -o link show | awk -F': ' '$2 !~ /^lo/ {sub(/@.*/, \"\", $2); print $2; exit}'); " + tc
    r = docker(["run", "--rm", "--net", f"container:{cid}", "--cap-add", "NET_ADMIN", NETEM_IMAGE, "sh", "-c", script])
    if r.returncode != 0 and on:
        raise RuntimeError(f"tc failed: {r.stderr.strip()}")


def networks_of(cid: str) -> List[str]:
    out = docker(["inspect", "-f", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}", cid]).stdout
    return out.split()


def inject(fault: str, svc: str, file: str) -> Callable[[], None]:
    """Break svc with the given fault; return the function that repairs it."""
    if fault == "stop":
        compose(["stop", svc], file)

        def start() -> None:
            compose(["start", svc], file)
        return start
    cid = container_of(svc, file)
    if fault == "slow":
        netem(cid, True)
        return lambda: netem(cid, False)
    nets = networks_of(cid)
    for n in nets:
        docker(["network", "disconnect", n, cid]).check_returncode()

    def heal() -> None:
        for n in nets:
            # Reconnect with the service name as alias, or callers cannot resolve it again.
            docker(["network", "connect", "--alias", svc, n, cid])
    return heal


def fill_disk(path: str) -> Callable[[], None]:
    """Fill the filesystem holding path to FREE_LEFT bytes free (fallocate: instant, no real writes)."""
    free_left = 8 * 1024 * 1024
    size = shutil.disk_usage(os.path.dirname(path) or "/").free - free_left
    with open(path, "wb") as f:
        os.posix_fallocate(f.fileno(), 0, max(size, 0))
    return lambda: os.remove(path)


def wait_recovered(api: str, preview: str, token: str, limit: float = 120.0) -> None:
    """Wait until every probe is back to the nothing-broken row. Breakers stay open for their cool-down (Velaris 30 s) after
    a fault is repaired; probing the next fault before that would blame it for the previous one."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if probe_all(api, preview, token) == DESIGN["(nothing)"]:
            return
        time.sleep(5)
    print(f"WARNING: the stack did not recover within {limit:.0f} s; the next row may show the previous fault")


def run(api: str, preview: str, token: str, file: str, faults: List[str], disk_full: str = "",
        settle: float = 12.0) -> int:
    if not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        print("SKIP: Docker is not available (the in-process version runs in tests/test_blast_radius.py)")
        return 0
    base = probe_all(api, preview, token)
    if base["healthz"] != "up":
        print(f"SKIP: the stack is not reachable at {api} (start it with docker compose up -d)")
        return 0
    gaps: List[str] = compare("(nothing)", base)
    rows = {"(nothing)": base}
    plan = [(f, n) for f in faults for n in (("db", "redis", "velaris", "preview", "api") if f == "stop"
                                               else ("db", "redis", "velaris"))]
    for fault, name in plan:
        svc, row = SERVICE[name], (name if fault == "stop" else f"{fault} {name}")
        if not container_of(svc, file):
            print(f"skip {row}: service not running in this stack")
            continue
        heal = inject(fault, svc, file)
        try:
            time.sleep(settle)
            rows[row] = probe_all(api, preview, token)
            gaps += compare(row, rows[row])
        finally:
            heal()
            wait_recovered(api, preview, token)
    if disk_full:
        heal = fill_disk(disk_full)
        try:
            time.sleep(settle)
            rows["disk full"] = probe_all(api, preview, token)
            gaps += compare("disk full", rows["disk full"])
        finally:
            heal()
    print("| broken | " + " | ".join(PROBES) + " |\n|---|" + "---|" * len(PROBES))
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
    ap.add_argument("--faults", default="stop,slow,partition", help="comma list of stop, slow, partition")
    ap.add_argument("--disk-full", default="", metavar="PATH", help="also fill the filesystem holding PATH (needs root)")
    args = ap.parse_args(argv)
    if args.table:
        print(table(), end="")
        return 0
    if args.run:
        if not args.token:
            print("--token is required for the authenticated probes", file=sys.stderr)
            return 2
        faults = [f for f in args.faults.split(",") if f]
        unknown = set(faults) - {"stop", "slow", "partition"}
        if unknown:
            print(f"unknown fault(s): {sorted(unknown)}", file=sys.stderr)
            return 2
        return run(args.api, args.preview, args.token, args.compose_file, faults, args.disk_full)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
