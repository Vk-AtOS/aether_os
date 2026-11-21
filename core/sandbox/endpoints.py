"""Where a sandboxed app's port is published, and where the platform connects to reach it.

Two settings, both defaulting to 127.0.0.1 (a gateway running directly on the host):

  AETHER_SANDBOX_PUBLISH_IP     host address the Docker backend publishes the app port on.
  AETHER_SANDBOX_UPSTREAM_HOST  address the gateway / preview server / phase probes connect to.

When the gateway itself runs in a container (docker compose), 127.0.0.1 is that container,
not the host, so every probe got "Connection refused" although the app was up. There the
operator sets both (docs/ops/RUNBOOKS.md, "Sandbox reachability"):

  * Linux compose: PUBLISH_IP = UPSTREAM_HOST = the docker0 bridge address (172.17.0.1), a
    host-local address the API container can route to; host_firewall.sh drops packets for it
    that arrive from outside the host.
  * Docker Desktop: PUBLISH_IP unset (127.0.0.1), UPSTREAM_HOST = host.docker.internal.

Kept light (stdlib + core.errors): the preview server imports it too.
"""
from __future__ import annotations

import os

from aether_os.core.errors import SandboxViolation
from aether_os.core.sandbox.publish_addr import validate_publish_ip

DEFAULT_HOST = "127.0.0.1"


def _setting(name: str) -> str:
    """The env value, or the loopback default when unset OR empty (compose passes `${X:-}` as "")."""
    return (os.environ.get(name) or "").strip() or DEFAULT_HOST


def publish_ip() -> str:
    """Host address a sandbox app port is published on: loopback or a private Docker bridge address,
    validated by publish_addr.py (the same check host_firewall.sh runs). Raises SandboxViolation otherwise."""
    try:
        return validate_publish_ip(_setting("AETHER_SANDBOX_PUBLISH_IP"))
    except ValueError as exc:
        raise SandboxViolation(f"AETHER_SANDBOX_PUBLISH_IP refused: {exc}") from exc


def app_host() -> str:
    """Address the platform connects to for an app the sandbox started (probes, health checks, proxy)."""
    return _setting("AETHER_SANDBOX_UPSTREAM_HOST")


def app_url(port: int, path: str = "") -> str:
    """http://<app_host>:<port><path>"""
    return f"http://{app_host()}:{port}{path}"
