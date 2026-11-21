"""Hardening of the sandbox boundary: symlinks in the run dir, forged launch state, firewall proof."""
from __future__ import annotations

import json
import os
import sys

import pytest

from aether_os.core.errors import SandboxViolation
from aether_os.core.run_app import preview_state
from aether_os.core.run_app.safe_fs import open_log_fd, safe_read_text, safe_write_text
from aether_os.core.sandbox import isolation_probe as ip
from aether_os.core.sandbox.runner import Limits, NoSandboxRunner


# ── item 9: a symlink planted in the run dir must not redirect gateway writes ──────────

@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "projects" / "run1"
    d.mkdir(parents=True)
    return d


def test_write_through_planted_symlink_is_refused(run_dir, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("platform file")
    (run_dir / "tsconfig.json").symlink_to(victim)
    with pytest.raises(SandboxViolation):
        safe_write_text(run_dir, run_dir / "tsconfig.json", "{}")
    with pytest.raises(SandboxViolation):
        safe_read_text(run_dir, run_dir / "tsconfig.json")
    assert victim.read_text() == "platform file"


def test_write_through_symlinked_directory_is_refused(run_dir, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (run_dir / "_preview_stub").symlink_to(outside)
    with pytest.raises(SandboxViolation):
        safe_write_text(run_dir, run_dir / "_preview_stub" / "main.py", "x")
    assert not (outside / "main.py").exists()


def test_plain_files_still_work(run_dir):
    safe_write_text(run_dir, run_dir / "a.txt", "hello")
    assert safe_read_text(run_dir, run_dir / "a.txt") == "hello"


def test_app_log_open_never_follows_a_symlink(run_dir, tmp_path):
    victim = tmp_path / "victim.log"
    victim.write_text("keep")
    (run_dir / "run_app.log").symlink_to(victim)
    with pytest.raises(SandboxViolation):
        open_log_fd(run_dir / "run_app.log")
    runner = NoSandboxRunner(Limits())
    with pytest.raises(SandboxViolation):
        runner.start([sys.executable, "-c", "print('pwn')"], run_dir=run_dir, cwd=run_dir, env={},
                     log_path=run_dir / "run_app.log", port=1, labels={})
    assert victim.read_text() == "keep"


# ── item 11: launch state is gateway-owned, nonce is not on the command line ───────────

def test_state_and_platform_log_live_outside_the_run_dir(tmp_path, monkeypatch):
    from aether_os.core import projects
    monkeypatch.setattr(projects, "_manager", projects.ProjectManager(tmp_path / "projects"))
    path = preview_state.state_path("run1")
    assert not path.is_relative_to(projects.get_project_manager().get_project_dir("run1"))
    assert preview_state.state_dir("run1") / "platform.log" != path


def test_nonce_is_passed_by_environment_not_argv():
    env = preview_state.nonce_env("a" * 32)
    assert env == {"UVICORN_HEADERS": f"{preview_state.NONCE_HEADER}:{'a' * 32}"}
    assert not hasattr(preview_state, "nonce_args")


@pytest.mark.parametrize("port,ok", [(20000, True), (29999, True), (19999, False), (30000, False),
                                     (5432, False), (6379, False), (8000, False), ("20001", False),
                                     (None, False), (True, False)])
def test_proxy_refuses_ports_outside_the_app_range(port, ok):
    assert preview_state.port_allowed(port) is ok


def test_read_launch_refuses_a_port_outside_the_range(tmp_path, monkeypatch):
    from aether_os.core import projects
    monkeypatch.setattr(projects, "_manager", projects.ProjectManager(tmp_path / "projects"))
    path = preview_state.state_path("r")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"port": 5432, "nonce": "n" * 32, "container": "c"}))
    assert preview_state.read_launch("r") is None
    path.write_text(json.dumps({"port": 20500, "nonce": "n" * 32, "container": "c"}))
    assert preview_state.read_launch("r") == {"port": 20500, "nonce": "n" * 32}


def test_pid_identity_is_start_time_not_command_line():
    started = preview_state.process_started(os.getpid())
    assert started and preview_state.is_launched_process(os.getpid(), started)
    assert not preview_state.is_launched_process(os.getpid(), "Thu Jan  1 00:00:00 1970")
    assert not preview_state.is_launched_process(os.getpid(), None)


def test_free_port_comes_from_the_app_range():
    from aether_os.core.services.run_app_service import _free_port
    assert preview_state.port_allowed(_free_port())


# ── item 10: the firewall is verified, not assumed ─────────────────────────────────────

class FakeDocker:
    """Fake `docker` CLI. `reach` = targets the probe container can connect to."""

    def __init__(self, reach=(), probe_code=0, probe_out=None):
        self.reach, self.probe_code, self.probe_out, self.calls = set(reach), probe_code, probe_out, []

    def __call__(self, args):
        self.calls.append(list(args))
        if args[0] == "network":
            return 0, "172.30.0.1 "
        wanted = list(args[args.index("-c") + 2:])
        out = self.probe_out if self.probe_out is not None else json.dumps({t: t in self.reach for t in wanted})
        return self.probe_code, out + "\n"


@pytest.fixture(autouse=True)
def _no_cache():
    ip.reset_cache()
    yield
    ip.reset_cache()


def _problem(fake, **kw):
    return ip.isolation_problem(fake, image="img", user="1000:1000",
                                networks={"run": False, "egress": True}, **kw)


def test_isolated_networks_verify():
    assert _problem(FakeDocker()) is None


@pytest.mark.parametrize("leak", ["172.30.0.1:5432", "169.254.169.254:80", "1.1.1.1:443"])
def test_a_reachable_forbidden_target_fails_verification(leak):
    problem = _problem(FakeDocker(reach=[leak]))
    assert problem and leak in problem and "host_firewall.sh" in problem


def test_public_internet_is_only_forbidden_on_the_app_network():
    fake = FakeDocker(reach=["1.1.1.1:443"])
    # the egress network legitimately reaches the internet and is not even probed for it
    assert ip.check_network(fake, network="egress", image="i", user="u", internet_allowed=True) is None


@pytest.mark.parametrize("fake", [FakeDocker(probe_code=125), FakeDocker(probe_out="not json"),
                                  FakeDocker(probe_out="{}"), FakeDocker(probe_out="")])
def test_a_probe_that_cannot_run_counts_as_failed(fake):
    assert "cannot verify" in (_problem(fake) or "")


def test_available_refuses_when_verification_fails(monkeypatch):
    from aether_os.core.sandbox import docker_backend as db
    ok = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    monkeypatch.setattr(db, "_docker", lambda *a, **k: ok)
    monkeypatch.setattr(db, "isolation_problem", lambda *a, **k: "network x can reach y")
    assert db.DockerRunner().available() is False
    monkeypatch.setattr(db, "isolation_problem", lambda *a, **k: None)
    assert db.DockerRunner().available() is True


def test_patch_generated_project_does_not_write_through_a_planted_symlink(tmp_path):
    from aether_os.core.run_app.process_manager_helpers import patch_generated_project
    root = tmp_path / "projects" / "run1"
    backend = root / "p04_backend" / "backend_codegen" / "app"
    (backend / "src").mkdir(parents=True)
    victim = tmp_path / "platform_secret.py"
    victim.write_text("SECRET = 1\n")
    (backend / "src" / "main.py").symlink_to(victim)          # planted by the sandboxed app
    with pytest.raises(SandboxViolation):
        patch_generated_project(backend_dir=backend, root_dir=root, frontend_dir=None, frontend_dist=None,
                                log_path=tmp_path / "platform.log")
    assert victim.read_text() == "SECRET = 1\n"


def test_patched_preview_app_never_allows_credentials_from_any_origin(tmp_path):
    # KAN-190: '*' with allow_credentials=True made Starlette reflect the caller's Origin, so any
    # website could make logged-in requests to a preview app and read the answers.
    from aether_os.core.run_app.process_manager_helpers import patch_generated_project
    root = tmp_path / "projects" / "run1"
    backend = root / "p04_backend" / "backend_codegen" / "app"
    (backend / "src").mkdir(parents=True)
    main_py = backend / "src" / "main.py"
    main_py.write_text("@app.get('/ping')\ndef ping():\n    return {}\n")   # no app = FastAPI(): boilerplate added
    patch_generated_project(backend_dir=backend, root_dir=root, frontend_dir=None, frontend_dist=None,
                            log_path=tmp_path / "platform.log")
    patched = "".join(p.read_text() for p in root.rglob("main.py"))
    assert "CORSMiddleware" in patched
    assert "allow_credentials=True" not in patched


def test_install_network_allows_dns_only_to_the_host_resolver():
    """AWS testbed run 8 (22 Nov 2026): the VPC resolver (172.31.0.2) is in a blocked private range, so every lookup from
    the install network failed and npm install hung until its 300 s timeout. The firewall must open port 53 to the
    configured resolver(s) only, ahead of the private-range drops, and never for the app network."""
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "core" / "sandbox" / "host_firewall.sh").read_text()
    dns_rule = 'rule DOCKER-USER -i "$EGR_IF" -d "$NS" -p "$PROTO" --dport 53 -j RETURN'
    assert dns_rule in script
    # rule() inserts at position 1, so the DNS allowance must be added AFTER the drop loop to end up above it
    assert script.index(dns_rule) > script.index('rule DOCKER-USER -i "$EGR_IF" -d "$CIDR" -j DROP')
    assert '$RUN_IF" -d "$NS"' not in script and "--dport 53" not in script.split("# Install network")[0]
    assert "!~ /^127\\./" in script   # never the loopback stub resolver
