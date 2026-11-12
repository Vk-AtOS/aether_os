"""Proof that the Docker sandbox networks are really isolated, before any generated code runs.

core/sandbox/host_firewall.sh is a manual, root-only step. If it was never applied (new host,
reboot without persistence, rules flushed) the bridge networks exist and everything "works",
but a generated app could reach the host, Postgres, Redis or cloud metadata. So DockerRunner
.available() does not trust that the script ran: it starts a short probe container on each
sandbox network and requires every forbidden connection to FAIL:

  both networks   the bridge gateway (= the host), and 169.254.169.254 (cloud metadata)
  app network     additionally the public internet (it has no egress at all)

A probe that cannot run, or whose output is not the expected JSON, counts as failed:
unverified means refuse. A pass is cached for a minute so every command does not pay for it.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

METADATA_IP = "169.254.169.254"
PUBLIC_IP = "1.1.1.1"
CACHE_TTL_S = 60
_passed_at: Dict[str, float] = {}

# Runs inside the probe container; prints {"<target>": true|false} where true = connected.
PROBE_SCRIPT = (
    "import json,socket,sys\n"
    "out={}\n"
    "for t in sys.argv[1:]:\n"
    "    host,port=t.rsplit(':',1)\n"
    "    s=socket.socket(); s.settimeout(3)\n"
    "    try:\n"
    "        s.connect((host,int(port))); out[t]=True\n"
    "    except OSError:\n"
    "        out[t]=False\n"
    "    finally:\n"
    "        s.close()\n"
    "print(json.dumps(out))\n"
)

# (network name, extra forbidden target: the public internet where the network has no egress)
Run = Callable[[Sequence[str]], Tuple[int, str]]  # docker CLI argv -> (returncode, stdout)


def targets(gateway_ip: str, internet_allowed: bool) -> List[str]:
    found = [f"{gateway_ip}:22", f"{gateway_ip}:5432", f"{gateway_ip}:6379", f"{gateway_ip}:8000",
             f"{METADATA_IP}:80"]
    return found if internet_allowed else found + [f"{PUBLIC_IP}:443"]


def check_network(run: Run, *, network: str, image: str, user: str, internet_allowed: bool) -> Optional[str]:
    """Why this network is not isolated (or could not be verified), or None when verified."""
    code, out = run(["network", "inspect", "-f",
                     "{{range .IPAM.Config}}{{.Gateway}} {{end}}", network])
    gateway = (out.split() or [""])[0]
    if code != 0 or not gateway:
        return f"cannot read the gateway address of network {network}"
    wanted = targets(gateway, internet_allowed)
    code, out = run(["run", "--rm", "--network", network, "--user", user, "--cap-drop", "ALL",
                     "--security-opt", "no-new-privileges", "--read-only", "--memory", "64m",
                     image, "python3", "-c", PROBE_SCRIPT, *wanted])
    try:
        result = json.loads(out.strip().splitlines()[-1]) if code == 0 and out.strip() else None
    except (ValueError, IndexError):
        result = None
    if not isinstance(result, dict) or set(result) != set(wanted):
        return f"isolation probe on {network} did not run (exit {code}); cannot verify the firewall"
    reachable = sorted(t for t, connected in result.items() if connected is not False)
    if reachable:
        return (f"network {network} can reach {', '.join(reachable)}: host_firewall.sh is not applied "
                "on this host (run it as root and keep it persistent)")
    return None


def isolation_problem(run: Run, *, image: str, user: str, networks: Dict[str, bool],
                      now: Optional[float] = None) -> Optional[str]:
    """First problem across the sandbox networks, or None. `networks` maps name -> internet allowed."""
    now = time.time() if now is None else now
    for name, internet in networks.items():
        if now - _passed_at.get(name, 0.0) < CACHE_TTL_S:
            continue
        problem = check_network(run, network=name, image=image, user=user, internet_allowed=internet)
        if problem:
            _passed_at.pop(name, None)
            return problem
        _passed_at[name] = now
    return None


def reset_cache() -> None:
    _passed_at.clear()
