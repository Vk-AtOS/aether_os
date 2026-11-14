"""Structural checks for the deploy files (nginx -t / docker / helm cannot run in CI here)."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


def _nginx():
    return re.sub(r"#[^\n]*", "", (DEPLOY / "nginx.conf").read_text())


def test_nginx_is_an_http_fragment_with_balanced_braces():
    conf = _nginx()
    assert conf.count("{") == conf.count("}")
    # included from nginx.conf's http{} via sites-enabled: these would fail `nginx -t`
    assert not re.search(r"^\s*(events|http)\s*\{", conf, re.M)
    assert not re.search(r"^\s*worker_(processes|rlimit_nofile)", conf, re.M)
    assert "upstream aetheros_backend" in conf


def test_nginx_servers_are_complete_and_zones_defined():
    conf = _nginx()
    servers = re.split(r"\n\s*server\s*\{", conf)[1:]
    assert len(servers) == 4
    for s in servers:
        assert "listen " in s and "server_name " in s
    for zone in set(re.findall(r"limit_req\s+zone=(\w+)", conf)):
        assert f"zone={zone}:" in conf
    assert "zone=perip:" in conf


def test_nginx_locations_do_not_drop_security_headers_or_set_content_type():
    conf = _nginx()
    # add_header inside a location replaces all server-level add_header (HSTS/CSP lost)
    for loc in re.findall(r"location[^{]*\{([^}]*)\}", conf):
        assert "add_header" not in loc
    assert "text/event-stream" not in conf


def test_nginx_dashboard_root_matches_install_dir_of_the_unit():
    unit = (DEPLOY / "aetheros.service").read_text()
    wd = re.search(r"WorkingDirectory=(\S+)", unit).group(1)
    assert f"root {wd}/dashboard/dist;" in _nginx()
    setup = (DEPLOY / "setup_vps.sh").read_text()
    assert f"INSTALL_DIR={wd}\n" in setup
    assert f"PYTHONPATH={Path(wd).parent}" in unit


def test_setup_vps_replaces_both_placeholders():
    setup = (DEPLOY / "setup_vps.sh").read_text()
    assert "PREVIEW_DOMAIN_PLACEHOLDER" in setup and "APP_DOMAIN_PLACEHOLDER" in setup
    deploy = (DEPLOY / "deploy.sh").read_text()
    assert "PREVIEW_DOMAIN_PLACEHOLDER" in deploy


def test_deploy_sh_migrates_to_head_and_fails_on_error():
    s = (DEPLOY / "deploy.sh").read_text()
    assert "alembic upgrade head" in s
    assert "revision_merge_guardian_heads" not in s
    line = next(l for l in s.splitlines() if "alembic upgrade head" in l)
    assert "||" not in line  # a failed migration must stop the deploy (set -e)


def _compose(name):
    return yaml.safe_load((ROOT / name).read_text())


def test_compose_has_no_default_db_password_and_redis_never_evicts():
    for name in ("docker-compose.yml", "docker-compose.staging.yml"):
        text = (ROOT / name).read_text()
        assert "aether_dev_pass" not in text
        assert "allkeys-lru" not in text and "noeviction" in text
        assert re.search(r"POSTGRES_PASSWORD:\?", text)


def test_staging_publishes_no_database_or_redis_port_and_does_not_mount_root():
    text = (ROOT / "docker-compose.staging.yml").read_text()
    svc = _compose("docker-compose.staging.yml")["services"]
    for name in ("db_staging", "redis_staging"):
        assert "ports" not in svc[name]
    assert "/root" not in text
    assert all(p.startswith("127.0.0.1:") for p in svc["api_staging"]["ports"])


def test_velaris_is_an_optional_profile_with_required_secret():
    v = _compose("docker-compose.yml")["services"]["velaris"]
    assert v["profiles"] == ["velaris"]
    assert "VELARIS_API_SECRET:?" in (ROOT / "docker-compose.yml").read_text()


def test_helm_and_k8s_carry_field_key_preview_and_velaris():
    for f in ("helm/aetheros/templates/secret.yaml", "deploy/kubernetes/secret.yaml"):
        t = (ROOT / f).read_text()
        assert "AETHER_FIELD_KEY" in t and "AETHER_PREVIEW_SECRET" in t and "VELARIS_API_SECRET" in t
    assert "VELARIS_API_URL" in (ROOT / "helm/aetheros/templates/configmap.yaml").read_text()
    assert "allkeys-lru" not in (ROOT / "helm/aetheros/values.yaml").read_text()
    assert "allkeys-lru" not in (ROOT / "deploy/kubernetes/redis.yaml").read_text()


def test_local_sh_velaris_port_does_not_collide_with_preview():
    s = (ROOT / "scripts/local.sh").read_text()
    assert "VELARIS_API_URL:-http://127.0.0.1:8730" in s


def test_ci_is_blocking_and_scans():
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    text = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "|| true" not in text
    for needle in ("pip-audit", "bandit", "gitleaks", "cov-fail-under", "postgres:15", "npm run build"):
        assert needle in text
    assert ci["permissions"] == {"contents": "read"}


def test_generate_workflow_is_hardened():
    text = (ROOT / ".github/workflows/aetheros-generate.yml").read_text()
    wf = yaml.safe_load(text)
    job = wf["jobs"]["generate"]
    assert "timeout-minutes" in job and "permissions" in wf
    assert any("checkout" in s.get("uses", "") for s in job["steps"])
    assert "maintainer-approved" in job["if"]
    assert "UNTRUSTED" in text and "${{ github.event.issue.body }}" not in text.split("run:")[1]
