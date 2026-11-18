"""KAN-128: the Velaris public host. Structural checks (nginx is not installed in CI); `nginx -t` runs when it is."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "deploy" / "nginx_velaris_public.conf"
PROXY = ROOT / "deploy" / "velaris_public_proxy.conf"


def _strip(path: Path) -> str:
    return re.sub(r"#[^\n]*", "", path.read_text())


def test_only_the_four_public_prefixes_are_proxied_and_everything_else_is_404():
    conf = _strip(CONF)
    locs = re.findall(r"location\s+(\^~\s+)?(=\s+)?(\S+)\s*\{([^}]*)\}", conf)
    proxied = sorted(p for _, _, p, body in locs if "proxy_pass" in body)
    assert proxied == ["/careers/", "/interview/", "/schedule/", "/sign/"]
    root = [body for _, _, p, body in locs if p == "/"]
    assert root and "return 404" in root[-1]   # the HTTPS server's catch-all is the last one
    assert "proxy_pass" in conf and conf.count("proxy_pass") == 4


def test_credentials_are_dropped_and_forwarded_for_is_replaced_not_appended():
    p = _strip(PROXY)
    for h in ("Cookie", "Authorization", "X-Api-Key", "X-Org-Id", "X-Velaris-Identity", "X-Velaris-Signature"):
        assert re.search(rf'proxy_set_header\s+{h}\s+"";', p), h
    assert re.search(r"proxy_set_header\s+X-Forwarded-For\s+\$remote_addr;", p)
    assert "proxy_add_x_forwarded_for" not in p
    assert "limit_req zone=vpub" in p and "proxy_read_timeout" in p and "proxy_connect_timeout" in p
    assert "limit_except GET HEAD POST OPTIONS" in p


def test_access_log_never_carries_a_token():
    conf = _strip(CONF)
    fmt = re.search(r"log_format\s+velaris_public\s+(.*?);", conf, re.S).group(1)
    for leak in ("$request ", '$request"', "$request_uri", "$uri", "$args", "$query_string", "$http_referer", "$http_cookie"):
        assert leak not in fmt, leak
    assert "$vpub_log_path" in fmt and "access_log /var/log/nginx/velaris_public_access.log velaris_public" in conf
    # the map, run as the same regex, keeps only the fixed first segment
    rx = re.search(r"~(\^\(\?<vpub_seg>[^\s]+)\s", conf).group(1).replace("(?<", "(?P<")
    for uri, want in (("/sign/SECRETtoken123/doc", "/sign"), ("/schedule/tok", "/schedule"), ("/careers/acme/jobs", "/careers"),
                      ("/interview/abc", "/interview"), ("/sign", "/sign")):
        m = re.match(rx, uri)
        assert m and m.group("vpub_seg") == want, uri
    assert not re.match(rx, "/agents/x") and not re.match(rx, "/signup/x")      # falls to the default "/***"


def test_headers_body_cap_and_tls():
    conf = _strip(CONF)
    assert "Referrer-Policy no-referrer" in conf and "client_max_body_size 256k" in conf
    assert "ssl_protocols       TLSv1.2 TLSv1.3" in conf and "Strict-Transport-Security" in conf
    for loc in re.findall(r"location[^{]*\{([^}]*)\}", conf):
        assert "add_header" not in loc            # would drop the server-level security headers
    assert conf.count("{") == conf.count("}") and not re.search(r"^\s*(events|http)\s*\{", conf, re.M)


def test_unit_and_compose_run_the_public_module_behind_one_proxy():
    unit = (ROOT / "deploy" / "velaris-public.service").read_text()
    assert "-m velaris.api.public" in unit and "VELARIS_PUBLIC_TRUST_PROXY=1" in unit
    svc = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["velaris_public"]
    assert svc["profiles"] == ["velaris"] and svc["ports"] == ["127.0.0.1:8731:8731"]
    assert svc["command"][-1] == "velaris.api.public" and svc["environment"]["VELARIS_PUBLIC_TRUST_PROXY"] == "1"


def test_setup_script_validates_the_domain_and_tests_before_reload():
    s = (ROOT / "deploy" / "velaris_public_setup.sh").read_text()
    assert "set -euo pipefail" in s and s.index("nginx -t") < s.index("systemctl reload nginx")
    assert "A-Za-z0-9.-" in s


@pytest.mark.skipif(shutil.which("nginx") is None, reason="nginx is not installed (UNVERIFIED here: run `nginx -t` on the host)")
def test_nginx_accepts_the_config(tmp_path):
    proxy = tmp_path / "velaris_public_proxy.conf"
    proxy.write_text(PROXY.read_text())
    site = CONF.read_text().replace("/etc/nginx/velaris_public_proxy.conf", str(proxy)).replace("VELARIS_PUBLIC_DOMAIN_PLACEHOLDER", "x.test")
    site = re.sub(r"ssl_certificate\s+\S+;|ssl_certificate_key\s+\S+;|access_log /var/log\S+ velaris_public;|error_log\s+\S+ crit;", "", site)
    site = site.replace("listen 443 ssl http2;", "listen 8443;").replace("listen [::]:443 ssl http2;", "")
    main = tmp_path / "nginx.conf"
    main.write_text(f"events {{}} http {{ {site} }}")
    # pid and error log inside tmp_path: the default /run/nginx.pid is not writable without root (failed on the CI runner)
    out = subprocess.run(["nginx", "-t", "-c", str(main), "-p", str(tmp_path), "-g", f"pid {tmp_path}/nginx.pid; error_log {tmp_path}/error.log;"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
