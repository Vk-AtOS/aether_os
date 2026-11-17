"""Check a user-supplied ssh git remote before the server connects to it (SSRF).

Both forms are parsed here, once: `ssh://[user@]host[:port]/path` and scp-style `[user@]host:path`. The host is then
resolved and checked with the SAME check the HTTP paths use (safe_http.resolve_public), the port must be on a short
allow-list, and the returned address is what the clone connects to (HostName pinned, HostKeyAlias = the real host),
so DNS cannot be changed between the check and the connection.
"""
from __future__ import annotations

import os
import ipaddress
import re
import shlex
import urllib.parse
from dataclasses import dataclass
from typing import List

from aether_os.core.security.safe_http import UnsafeURL, resolve_public

_SCP = re.compile(r"^(?:(?P<user>[A-Za-z0-9._-]{1,64})@)?(?P<host>[A-Za-z0-9.-]{1,253}|\[[0-9A-Fa-f:.]+\]):(?P<path>[^:\s][^\s]*)$")
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")      # ASCII only: no spaces, quotes, ;, $, backticks, '-' first
_USER = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class SshRemote:
    host: str
    port: int
    address: str     # a public address `host` resolved to at check time


def _allowed_ports() -> List[int]:
    raw = os.environ.get("GIT_SSH_ALLOWED_PORTS", "22")
    return [int(p) for p in raw.split(",") if p.strip().isdigit()] or [22]


def parse_ssh_remote(url: str) -> tuple:
    """(host, port) of an ssh remote in either form. Raises UnsafeURL for anything else (local path, file://,
    ext::, http, leading '-', whitespace/control characters, credentials with ':' ...)."""
    url = (url or "").strip()
    if not url or url.startswith("-") or len(url) > 1024 or any(c.isspace() or ord(c) < 32 for c in url):
        raise UnsafeURL("not a git ssh remote")
    if "://" in url:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("ssh", "git+ssh", "ssh+git"):
            raise UnsafeURL("only ssh remotes are allowed")
        try:
            port = parts.port or 22
        except ValueError:
            raise UnsafeURL("invalid port") from None
        user = parts.username
        if (user is not None and not _USER.match(user)) or parts.password is not None:
            raise UnsafeURL("invalid user in the remote")
        host = (parts.hostname or "").lower()   # no rstrip: a trailing dot is refused below
    else:
        m = _SCP.match(url)
        if not m or url.startswith(("/", ".", "~")):
            raise UnsafeURL("not a git ssh remote")
        host, port = m.group("host").strip("[]").lower(), 22
    if not host:
        raise UnsafeURL("the remote has no host")
    _strict_host(host)
    return host, port


def _strict_host(host: str) -> None:
    """Both URL forms end here: the host is a plain DNS name or an IP literal, nothing else (it reaches a command line)."""
    if _HOST.fullmatch(host) and host.isascii():
        return
    try:
        ipaddress.ip_address(host)
    except ValueError:
        raise UnsafeURL("the remote host is not a valid host name") from None


def check_ssh_remote(url: str) -> SshRemote:
    """Parse, port-check, resolve and public-check. Blocking (DNS): call from a thread. Raises UnsafeURL."""
    host, port = parse_ssh_remote(url)
    if port not in _allowed_ports():
        raise UnsafeURL(f"port {port} is not allowed for git over ssh")
    netloc = f"[{host}]" if ":" in host else host
    _, addresses = resolve_public(f"http://{netloc}:{port}/")      # the one shared check (loopback, private, metadata ...)
    return SshRemote(host=host, port=port, address=addresses[0])


def check_https_remote(url: str) -> str:
    """The https counterpart of check_ssh_remote, for every clone or fetch of a user-supplied https URL: plain
    https on port 443, no credentials in the URL, a strict host name, and every address it resolves to public
    (the same safe_http.resolve_public check). Blocking (DNS): call from a thread. Returns the stripped URL.
    Raises UnsafeURL. Unlike ssh the connection cannot be pinned to the checked address, so DNS rebinding between
    this check and git's own lookup is a known residual; the allow-list callers add on top narrows it."""
    url = (url or "").strip()
    if not url or url.startswith("-") or len(url) > 1024 or any(c.isspace() or ord(c) < 32 for c in url):
        raise UnsafeURL("not a git https remote")
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        raise UnsafeURL("invalid port") from None
    if parts.scheme != "https" or parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UnsafeURL("only plain https remotes without credentials are allowed")
    if port not in (None, 443):
        raise UnsafeURL(f"port {port} is not allowed for git over https")
    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeURL("the remote has no host")
    _strict_host(host)
    resolve_public(url)
    return url


def ssh_command(key_file: str, remote: SshRemote) -> str:
    """GIT_SSH_COMMAND that connects to the CHECKED address, trusts no user config and no proxy."""
    # GIT_SSH_COMMAND goes through a shell: every element is quoted, the address is an ipaddress-validated literal
    # and the host/port were validated above, so nothing here can add a shell word or an ssh option.
    address = str(ipaddress.ip_address(remote.address.split("%", 1)[0]))
    _strict_host(remote.host)
    key = str(key_file)
    if not key.startswith("/") or "\x00" in key:
        raise UnsafeURL("invalid key path")
    return " ".join(shlex.quote(a) for a in [
        "ssh", "-F", "/dev/null", "-i", key, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ProxyCommand=none", "-o", "ProxyJump=none", "-o", "ConnectTimeout=15",
        "-o", f"HostName={address}", "-o", f"HostKeyAlias={remote.host}",
    ])
