"""Regression: the platform reaches sandboxed apps through core/sandbox/endpoints.py, never a hard-coded 127.0.0.1.

First real compose run: the API container started the generated backend through the host Docker socket, the app
logged "Database seeding complete", but the p04a probe connected to 127.0.0.1 (the API container itself) and got
"Connection refused" until "Server did not start in 8s" failed stage 3.
"""
from __future__ import annotations

import asyncio
import re
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from aether_os.core.errors import SandboxViolation
from aether_os.core.sandbox import docker_backend as db
from aether_os.core.sandbox import endpoints, phase_exec
from aether_os.phases.p04a_backend_codegen import helpers as p04a_helpers
from aether_os.phases.p07b_performance_testing import task_agent as perf_agent

_ROOT = Path(__file__).resolve().parent.parent
_ENV_VARS = ("AETHER_SANDBOX_UPSTREAM_HOST", "AETHER_SANDBOX_PUBLISH_IP")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ── endpoints ────────────────────────────────────────────────────────────────

def test_defaults_are_loopback_so_host_installs_behave_as_before():
    assert endpoints.app_host() == "127.0.0.1"
    assert endpoints.publish_ip() == "127.0.0.1"
    assert endpoints.app_url(8123, "/health") == "http://127.0.0.1:8123/health"
    assert phase_exec.app_host is endpoints.app_host


def test_empty_values_from_compose_mean_the_default(monkeypatch):
    # docker-compose passes `${X:-}` as an empty string; "" must not become "publish on every interface".
    monkeypatch.setenv("AETHER_SANDBOX_UPSTREAM_HOST", "")
    monkeypatch.setenv("AETHER_SANDBOX_PUBLISH_IP", "  ")
    assert endpoints.app_host() == "127.0.0.1"
    assert endpoints.publish_ip() == "127.0.0.1"


def test_env_override(monkeypatch):
    monkeypatch.setenv("AETHER_SANDBOX_UPSTREAM_HOST", "host.docker.internal")
    monkeypatch.setenv("AETHER_SANDBOX_PUBLISH_IP", "172.17.0.1")
    assert endpoints.app_host() == "host.docker.internal"
    assert endpoints.app_url(9000) == "http://host.docker.internal:9000"
    assert endpoints.publish_ip() == "172.17.0.1"


@pytest.mark.parametrize("wildcard", ["0.0.0.0", "::", "[::]", "*"])
def test_publish_ip_never_a_wildcard(monkeypatch, wildcard):
    monkeypatch.setenv("AETHER_SANDBOX_PUBLISH_IP", wildcard)
    with pytest.raises(SandboxViolation):
        endpoints.publish_ip()


def test_docker_backend_publishes_on_the_configured_ip(monkeypatch, tmp_path):
    monkeypatch.setenv("AETHER_SANDBOX_PUBLISH_IP", "172.17.0.1")
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        return subprocess.CompletedProcess(args, 0, "cid123\n", "")

    monkeypatch.setattr(db.subprocess, "run", fake_run)
    run_dir = tmp_path / "projects" / "run1"
    run_dir.mkdir(parents=True)
    proc = db.DockerRunner().start(["python3", "-V"], run_dir=run_dir, cwd=run_dir, env={},
                                   log_path=run_dir / "x.log", port=8123, labels={})
    args = seen["args"]
    assert args[args.index("--publish") + 1] == "172.17.0.1:8123:8123"
    assert proc.container_id == "cid123"

    monkeypatch.setenv("AETHER_SANDBOX_PUBLISH_IP", "0.0.0.0")
    with pytest.raises(SandboxViolation):
        db.DockerRunner().start(["python3", "-V"], run_dir=run_dir, cwd=run_dir, env={},
                                log_path=run_dir / "x.log", port=8123, labels={})


# ── call sites ───────────────────────────────────────────────────────────────

class _FakeProc:
    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def _recording_client(monkeypatch, urls: list):
    """httpx.AsyncClient that records request URLs and answers 200 without any network."""
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json={"status": "ok"})

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def test_p04a_live_probe_connects_to_the_upstream_host(monkeypatch, tmp_path):
    monkeypatch.setenv("AETHER_SANDBOX_UPSTREAM_HOST", "sandbox-upstream.test")
    src = tmp_path / "backend" / "src"
    src.mkdir(parents=True)
    port = 18765
    monkeypatch.setattr(p04a_helpers, "_free_port", lambda: port)
    monkeypatch.setattr(phase_exec, "start_app", lambda *a, **kw: _FakeProc())

    connects = []

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_connect(address, timeout=None, *a, **kw):
        connects.append(address)
        return _Conn()

    monkeypatch.setattr(socket, "create_connection", fake_connect)
    urls: list = []
    _recording_client(monkeypatch, urls)

    async def emit(_event):
        return None

    result = asyncio.run(p04a_helpers._live_http_probe(src, emit))
    assert connects and all(c == ("sandbox-upstream.test", port) for c in connects), connects
    assert urls and urls[0] == f"http://sandbox-upstream.test:{port}/health", urls
    assert all("127.0.0.1" not in u for u in urls)
    assert result["passed"] is True, result


def test_p07b_perf_hits_the_upstream_host(monkeypatch, tmp_path):
    monkeypatch.setenv("AETHER_SANDBOX_UPSTREAM_HOST", "sandbox-upstream.test")
    urls: list = []
    _recording_client(monkeypatch, urls)
    phase_input = SimpleNamespace(input_data={"backend_port": 19001, "project_name": "x"})
    asyncio.run(perf_agent.run(phase_input, [], tmp_path / "out"))
    assert urls and set(urls) == {"http://sandbox-upstream.test:19001/health"}, set(urls)


# Probes of sandbox-started apps must not hard-code loopback again (p04a, p07b quality probe, perf, p11).
_PROBE_FILES = [
    "phases/p04a_backend_codegen/helpers.py",
    "phases/p07b_self_healing/task_agent.py",
    "phases/p07b_performance_testing/task_agent.py",
    "phases/p11_deployment/helpers.py",
]
_LOOPBACK_CONNECT = re.compile(
    r"create_connection\(\(\s*[\"'](127\.0\.0\.1|localhost)[\"']"
    r"|https?://(127\.0\.0\.1|localhost):\{(probe_port|port|backend_port)\}"
    r"|[\"']-p[\"'],\s*f[\"']127\.0\.0\.1:"
)


@pytest.mark.parametrize("rel", _PROBE_FILES)
def test_no_hard_coded_loopback_probe(rel):
    text = (_ROOT / rel).read_text()
    assert not _LOOPBACK_CONNECT.search(text), f"{rel} connects to a sandboxed app on a hard-coded loopback address"
