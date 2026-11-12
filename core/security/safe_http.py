"""AetherOS — outbound HTTP to an address a user supplied (webhooks, self-hosted
services), without letting that user reach the platform's own network.

    resp = await safe_request("POST", url, content=body, headers=headers, timeout=10)

The hostname is resolved once; EVERY address it resolves to must be public, and the
connection is made to the checked address (not a fresh lookup), so a DNS answer that
changes between the check and the connect (rebinding) cannot redirect it. The
original hostname is still sent as the Host header and used for TLS SNI and
certificate verification. No redirects, no proxies from the environment.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import urllib.parse
from typing import Any, List, Tuple

import httpx

_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


class UnsafeURL(ValueError):
    """The URL may not be fetched: bad scheme, blocked host, or a non-public address."""


def _is_public(addr: ipaddress._BaseAddress) -> bool:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def check_url_shape(url: str) -> urllib.parse.SplitResult:
    """The checks that need no DNS (for saving a URL): http(s), a hostname, not a
    blocked name, not a literal non-public address. Raises UnsafeURL."""
    try:
        parsed = urllib.parse.urlsplit(url)
        parsed.port  # noqa: B018 — raises ValueError for a malformed port
    except ValueError as exc:
        raise UnsafeURL(f"malformed URL: {exc}") from exc
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURL("URL must use http or https")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURL("URL has no hostname")
    if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        raise UnsafeURL(f"blocked host: {host}")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        return parsed  # a name: resolved and checked when it is used
    if not _is_public(literal):
        raise UnsafeURL("URL must not target a private or reserved address")
    return parsed


def resolve_public(url: str) -> Tuple[urllib.parse.SplitResult, List[str]]:
    """(parsed url, resolved addresses), every one of them public. Blocking (DNS):
    call it from a thread on the event loop. Raises UnsafeURL otherwise."""
    parsed = check_url_shape(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError) as exc:
        raise UnsafeURL(f"cannot resolve {host!r}: {exc}") from exc
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise UnsafeURL(f"{host!r} has no address")
    for raw in addresses:
        if not _is_public(ipaddress.ip_address(raw.split("%", 1)[0])):
            raise UnsafeURL(f"{host!r} resolves to a non-public address ({raw})")
    return parsed, addresses


def _pinned_url(parsed: urllib.parse.SplitResult, address: str) -> str:
    netloc = f"[{address}]" if ":" in address else address
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))


async def safe_request(method: str, url: str, *, timeout: float = 10.0, **kwargs: Any) -> httpx.Response:
    """Send one request to a user-supplied URL, pinned to an address that passed the check.

    Raises UnsafeURL before any connection is made if the URL is not allowed; network
    errors propagate as httpx exceptions.
    """
    parsed, addresses = await asyncio.to_thread(resolve_public, url)
    host = parsed.hostname or ""
    headers = dict(kwargs.pop("headers", None) or {})
    headers["Host"] = host if parsed.port is None else f"{host}:{parsed.port}"
    extensions = {"sni_hostname": host} if parsed.scheme == "https" else {}
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        return await client.request(method, _pinned_url(parsed, addresses[0]), headers=headers,
                                    extensions=extensions, **kwargs)
