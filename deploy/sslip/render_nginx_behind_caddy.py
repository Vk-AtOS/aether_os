#!/usr/bin/env python3
"""Render deploy/nginx.conf for an install without its own domain, where Caddy terminates TLS (KAN-75).

Usage: render_nginx_behind_caddy.py <host> <out_nginx_conf> <out_caddyfile> [email]
  host: the public name, e.g. 3-105-82-63.sslip.io

deploy/nginx.conf stays the single source of the app's routing, rate limits and security headers. This script only:
  * drops the port-80 redirect server and both preview servers (Caddy redirects to HTTPS and serves previews itself),
  * makes the app server listen on 127.0.0.1:8080 without TLS (Caddy holds the certificate),
  * trusts X-Forwarded-For from 127.0.0.1 only, so per-client rate limits (limit_req/limit_conn) still see the real
    client address and not Caddy's,
  * forwards X-Forwarded-Proto https, because the scheme nginx sees is now http.
It refuses to write anything if the source no longer has the shape it expects, instead of emitting a broken proxy.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "nginx.conf"
CADDY_TEMPLATE = HERE / "Caddyfile.template"
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")


def _server_blocks(text: str) -> list[tuple[int, int]]:
    """(start, end) of every top-level `server { ... }` block, found by brace matching."""
    blocks, i = [], 0
    pattern = re.compile(r"(?m)^server\s*\{")
    while (m := pattern.search(text, i)):
        depth, j = 0, m.end() - 1
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            raise SystemExit("nginx.conf: unbalanced braces in a server block")
        blocks.append((m.start(), j + 1))
        i = j + 1
    return blocks


def render_nginx(source: str, host: str) -> str:
    blocks = _server_blocks(source)
    keep_app, out, pos = None, [], 0
    for start, end in blocks:
        body = source[start:end]
        out.append(source[pos:start])
        pos = end
        if re.search(r"server_name[^;]*PREVIEW_DOMAIN_PLACEHOLDER", body):
            continue                                           # preview servers: served by Caddy
        if re.search(r"listen\s+80;", body) and "return 301 https" in body:
            continue                                           # redirect: Caddy redirects
        if re.search(r"listen\s+443\s+ssl", body):
            keep_app = body
            body = re.sub(r"(?m)^\s*listen\s+(\[::\]:)?443\s+ssl[^;]*;\n", "", body)
            body = re.sub(r"(?m)^\s*ssl_[a-z_]+\s+[^;]*;\n", "", body)
            body = body.replace("server {", "server {\n    listen 127.0.0.1:8080;\n"
                                "    # Behind Caddy (deploy/sslip): trust the client address it forwards, from loopback only.\n"
                                "    set_real_ip_from 127.0.0.1;\n    real_ip_header X-Forwarded-For;\n", 1)
            body = re.sub(r"(X-Forwarded-Proto\s+)\$scheme", r"\1https", body)
        out.append(body)
    out.append(source[pos:])
    if keep_app is None:
        raise SystemExit("nginx.conf: no `listen 443 ssl` app server found; refusing to render")
    # The app server still names the preview base in its CSP (frame-src): same value bootstrap.sh uses.
    rendered = ("".join(out).replace("PREVIEW_DOMAIN_PLACEHOLDER", f"preview.{host}").replace("APP_DOMAIN_PLACEHOLDER", host)
                # Same default as deploy/deploy.sh; leaving the placeholder made browsers block every dashboard API call.
                .replace("CSP_CONNECT_SRC_PLACEHOLDER", "'self' https: wss: blob:"))
    if "PLACEHOLDER" in re.sub(r"(?m)^\s*#.*$", "", rendered) or re.search(r"listen\s+(\[::\]:)?(80|443)\b", rendered):
        raise SystemExit("nginx.conf: rendered config still binds port 80/443 or has an unfilled placeholder; refusing")
    return rendered


def render_caddy(template: str, host: str, email: str = "") -> str:
    host_re = re.escape(host).replace("\\-", "-")
    email_line = f"email {email}" if email else "# no ACME account e-mail configured"
    return (template.replace("__HOST_RE__", host_re.replace("\\", "\\\\"))
            .replace("__HOST__", host).replace("__EMAIL_LINE__", email_line))


def main(argv: list[str]) -> int:
    if len(argv) not in (4, 5):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    host, out_nginx, out_caddy = argv[1].lower(), Path(argv[2]), Path(argv[3])
    email = argv[4] if len(argv) == 5 else ""
    if not HOST_RE.match(host):
        raise SystemExit(f"not a host name: {host!r}")
    out_nginx.write_text(render_nginx(SOURCE.read_text(), host))
    out_caddy.write_text(render_caddy(CADDY_TEMPLATE.read_text(), host, email))
    print(f"rendered {out_nginx} and {out_caddy} for {host}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
