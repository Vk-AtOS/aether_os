#!/usr/bin/env python3.11
"""Check that a real preview origin has wildcard DNS and a valid wildcard certificate (KAN-75 staging test).

    python3.11 scripts/check_preview_origin.py https://preview.example.com [--min-days 14]

Exit 0 = all checks pass. Needs network. It resolves two random labels under the host, connects with TLS using
that label as SNI (so a certificate that covers only the bare host fails), and checks the expiry margin.
Read-only: it sends no HTTP request.
"""
from __future__ import annotations

import argparse
import secrets
import socket
import ssl
import sys
import time
from typing import List, Tuple
from urllib.parse import urlparse


def days_left(cert: dict, now: float | None = None) -> float:
    return (ssl.cert_time_to_seconds(cert["notAfter"]) - (time.time() if now is None else now)) / 86400


def check_cert(cert: dict, label_host: str, min_days: float, now: float | None = None) -> List[str]:
    """Problems with a peer certificate dict (as returned by SSLSocket.getpeercert) for `label_host`."""
    problems = []
    if not _matches(cert, label_host):
        problems.append(f"certificate does not cover {label_host}")
    left = days_left(cert, now)
    if left < min_days:
        problems.append(f"certificate expires in {left:.0f} days (minimum {min_days:g})")
    return problems


def _matches(cert: dict, host: str) -> bool:
    for kind, name in cert.get("subjectAltName", ()):
        if kind != "DNS":
            continue
        if name == host:
            return True
        if name.startswith("*.") and host.count(".") == name.count(".") and host.split(".", 1)[1] == name[2:]:
            return True
    return False


def run(origin: str, min_days: float = 14) -> Tuple[bool, List[str]]:
    host = urlparse(origin).hostname
    if not host or urlparse(origin).scheme != "https":
        return False, ["origin must be an https URL"]
    problems: List[str] = []
    ips = set()
    for _ in range(2):
        label = f"chk-{secrets.token_hex(4)}.{host}"
        try:
            ips.add(socket.gethostbyname(label))
        except OSError:
            problems.append(f"no wildcard DNS record: {label} does not resolve")
    try:
        base_ip = socket.gethostbyname(host)
        if ips and ips != {base_ip}:
            problems.append("wildcard record points somewhere other than the base host")
    except OSError:
        problems.append(f"{host} does not resolve")
    label = f"chk-{secrets.token_hex(4)}.{host}"
    try:
        with socket.create_connection((host, 443), timeout=10) as raw:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(raw, server_hostname=label) as tls:
                problems += check_cert(tls.getpeercert(), label, min_days)
    except (OSError, ssl.SSLError) as e:
        problems.append(f"TLS handshake for {label} failed: {type(e).__name__}: {e}")
    return not problems, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("origin")
    ap.add_argument("--min-days", type=float, default=14)
    args = ap.parse_args()
    ok, problems = run(args.origin, args.min_days)
    for p in problems:
        print("FAIL:", p)
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
