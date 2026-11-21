"""KAN-65/66/101: the API never mounts the host Docker socket; a filtered proxy does."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOC = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
COMPOSE = DOC["services"]
PROXY = COMPOSE["docker-proxy"]


def test_only_the_proxy_mounts_the_docker_socket_and_read_only():
    holders = [n for n, d in COMPOSE.items() if any("docker.sock" in str(v) for v in d.get("volumes", []))]
    assert holders == ["docker-proxy"]
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in PROXY["volumes"]


def test_api_reaches_docker_through_the_proxy_without_the_docker_group():
    api = COMPOSE["api"]
    assert api["environment"]["DOCKER_HOST"] == "tcp://docker-proxy:2375"
    assert "group_add" not in api and "docker-proxy" in api["depends_on"]
    assert "sandbox_ctl" in api["networks"]


def test_proxy_allows_only_what_docker_backend_uses():
    env = PROXY["environment"]
    for allowed in ("CONTAINERS", "IMAGES", "NETWORKS", "INFO", "POST"):
        assert env[allowed] == "1"
    for denied in ("EXEC", "VOLUMES", "BUILD", "SWARM", "SECRETS", "PLUGINS", "SYSTEM", "SERVICES", "CONFIGS", "SESSION"):
        assert env[denied] == "0", denied


def test_proxy_is_on_an_internal_network_only_and_hardened():
    assert PROXY["networks"] == ["sandbox_ctl"]
    assert "ports" not in PROXY
    assert DOC["networks"]["sandbox_ctl"]["internal"] is True
    assert PROXY["read_only"] is True and PROXY["cap_drop"] == ["ALL"]
    assert "@sha256:" in PROXY["image"]
    assert {n for n, d in COMPOSE.items() if "sandbox_ctl" in d.get("networks", [])} == {"api", "docker-proxy"}


def test_docker_cli_honours_docker_host():
    # root cause guard: docker_backend must not pass --host/-H or scrub the environment, or DOCKER_HOST is ignored
    src = (ROOT / "core/sandbox/docker_backend.py").read_text()
    assert "--host" not in src and '"-H"' not in src
    assert "env=" not in src.split("def _docker(")[1].split("\ndef ")[0]
