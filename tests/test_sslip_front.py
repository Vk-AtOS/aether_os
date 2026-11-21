"""deploy/sslip: Caddy terminates TLS (per-run preview certificates on demand) and nginx runs behind it (KAN-75)."""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sslip_render", ROOT / "deploy" / "sslip" / "render_nginx_behind_caddy.py")
render = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render)
HOST = "3-105-82-63.sslip.io"


def test_nginx_behind_caddy_keeps_the_app_and_drops_tls_and_previews():
    rendered = render.render_nginx((ROOT / "deploy" / "nginx.conf").read_text(), HOST)
    out = "\n".join(line for line in rendered.splitlines() if not line.lstrip().startswith("#"))   # directives only
    assert "listen 127.0.0.1:8080;" in out
    assert not re.search(r"listen\s+(\[::\]:)?(80|443)\b", out)          # Caddy owns the public ports
    assert "ssl_certificate" not in out and "PLACEHOLDER" not in out
    assert "set_real_ip_from 127.0.0.1;" in out and "real_ip_header X-Forwarded-For;" in out   # per-IP limits still work
    assert "X-Forwarded-Proto $scheme" not in out and "X-Forwarded-Proto https" in out
    assert "proxy_pass         http://127.0.0.1:8100" not in out          # previews are served by Caddy
    assert "limit_req" in out and "location /api/" in out                  # the app server itself is intact


def test_caddy_only_issues_certificates_for_run_preview_hosts():
    caddy = render.render_caddy((ROOT / "deploy" / "sslip" / "Caddyfile.template").read_text(), HOST)
    assert "__HOST" not in caddy and "__EMAIL" not in caddy
    pattern = re.search(r'matches\("(.+?)"\)', caddy).group(1).replace("\\\\", "\\")
    ok = re.compile(pattern)
    assert ok.match(f"0b6a2c1e-1111-2222-3333-444455556666.preview.{HOST}")
    for bad in ("evil.example.com", f"x.y.preview.{HOST}", f"preview.{HOST}.evil.com", f"-x.preview.{HOST}", HOST):
        assert not ok.match(bad), bad
    assert "header_up -X-Api-Key" in caddy and "header_up -X-Org-Id" in caddy
    assert "bind 127.0.0.1" in caddy                                       # the ask endpoint is loopback only


def test_render_refuses_a_source_without_an_app_server():
    import pytest
    with pytest.raises(SystemExit):
        render.render_nginx("server {\n    listen 80;\n    return 301 https://$host$request_uri;\n}\n", HOST)


def test_velaris_public_behind_caddy_keeps_its_allowlist_and_scrubbing():
    conf, proxy = render.render_velaris_public((ROOT / "deploy" / "nginx_velaris_public.conf").read_text(),
                                               (ROOT / "deploy" / "velaris_public_proxy.conf").read_text(), HOST)
    directives = "\n".join(l for l in conf.splitlines() if not l.lstrip().startswith("#"))
    assert "listen 127.0.0.1:8081;" in directives and not re.search(r"listen\s+(\[::\]:)?(80|443)\b", directives)
    assert f"server_name velaris.{HOST};" in directives and "PLACEHOLDER" not in directives
    for path in ("/careers/", "/schedule/", "/interview/", "/sign/"):
        assert f"location ^~ {path}" in directives
    assert "location /          { return 404; }" in directives            # everything else stays closed
    assert "log_format velaris_public" in directives                       # masked access log kept
    assert "X-Forwarded-Proto https" in proxy and 'proxy_set_header Authorization "";' in proxy


def test_caddy_serves_the_velaris_public_host():
    caddy = render.render_caddy((ROOT / "deploy" / "sslip" / "Caddyfile.template").read_text(), HOST)
    assert f"velaris.{HOST} {{" in caddy and "reverse_proxy 127.0.0.1:8081" in caddy
