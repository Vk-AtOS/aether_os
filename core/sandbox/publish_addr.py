"""Validation of AETHER_SANDBOX_PUBLISH_IP, the host address untrusted generated apps are published on.

Standard library only, and runnable as a script, so the gateway (core/sandbox/endpoints.py) and
core/sandbox/host_firewall.sh apply the SAME rule and cannot disagree:

    python3 core/sandbox/publish_addr.py <address>   -> prints the canonical address, exit 0; else exit 1

Allowed:
  * loopback (127.0.0.0/8, ::1): unreachable from outside the host by construction (the default);
  * an IPv4 address in RFC 1918 space (10/8, 172.16/12, 192.168/16): Docker allocates docker0 and
    compose bridge gateways from these pools, which is what a containerised gateway needs.
Everything else is refused: unparsable text and hostnames (no DNS surprises; "0" and "000.0.0.0"
are not accepted spellings), the unspecified address in any spelling ("0.0.0.0", "::", "::0",
"0:0:0:0:0:0:0:0", "[0::0]") which publishes on every interface, link-local (169.254/16, the cloud
metadata range), multicast, CGNAT/reserved ranges, every public address, and non-loopback IPv6
(the sandbox firewall is IPv4-only).

RFC 1918 also covers a host's own LAN/VPC address, which IS reachable from outside. The prefix cannot
tell those apart, so host_firewall.sh additionally requires the address to be assigned to docker0 or a
Docker bridge (br-*) and drops packets for it that arrive on any other interface.
"""
from __future__ import annotations

import ipaddress
import sys

_RFC1918 = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def validate_publish_ip(value: str) -> str:
    """The canonical form of an acceptable publish address; raises ValueError otherwise."""
    text = (value or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        raise ValueError(f"publish address {value!r} is not an IP address") from None
    if ip.is_unspecified:
        raise ValueError(f"publish address {value!r} is the wildcard address: it would expose apps on every interface")
    if ip.is_loopback:
        return str(ip)
    if ip.version == 4 and any(ip in net for net in _RFC1918):
        return str(ip)
    raise ValueError(f"publish address {value!r} must be loopback or a private (RFC 1918) Docker bridge address")


def main(argv: list) -> int:
    if len(argv) != 2:
        print("usage: publish_addr.py <address>", file=sys.stderr)
        return 2
    try:
        print(validate_publish_ip(argv[1]))
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
