"""Sandbox policy: the docker run arguments (pure) and the backend selection (fail closed).

The argument tests need no Docker. The one live test runs a real container and is
skipped when the Docker daemon or the sandbox image is not available.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from aether_os.core.sandbox import docker_backend as db
from aether_os.core.sandbox import runner as rn
from aether_os.core.sandbox.runner import Limits, SandboxUnavailable, SandboxViolation, get_runner

RUN = Path("/home/aether/.aether_os/projects/run-1")
LIMITS = Limits(memory_mb=512, cpus=0.5, pids=128)


def _args(**kw):
    base = dict(name="aether-sbx-x", run_dir=RUN, cwd=RUN / "backend", argv=["python3", "-V"],
                env={"PATH": "/host/bin", "DATABASE_URL": "sqlite:///x.db", "HOME": str(RUN / ".h")},
                limits=LIMITS, network="none", user="1000:1000", img="aether-sandbox:1")
    base.update(kw)
    return db.docker_args(**base)


def _pairs(args, flag):
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


def test_container_is_locked_down():
    args = _args()
    assert args[:3] == ["docker", "run", "--rm"]
    assert "--read-only" in args
    assert _pairs(args, "--cap-drop") == ["ALL"]
    assert "--cap-add" not in args and "--privileged" not in args
    assert _pairs(args, "--security-opt") == ["no-new-privileges"]   # default seccomp: never unconfined
    assert not any("unconfined" in a for a in args)
    assert _pairs(args, "--user") == ["1000:1000"]
    assert _pairs(args, "--memory") == ["512m"] and _pairs(args, "--memory-swap") == ["512m"]
    assert _pairs(args, "--cpus") == ["0.5"] and _pairs(args, "--pids-limit") == ["128"]
    assert any(u.startswith("fsize=") for u in _pairs(args, "--ulimit"))
    assert args[-3:] == ["aether-sandbox:1", "python3", "-V"]


def test_only_the_run_dir_is_mounted():
    args = _args()
    assert "-v" not in args and "--volume" not in args and "--volumes-from" not in args
    assert _pairs(args, "--mount") == [f"type=bind,src={RUN},dst={RUN}"]
    assert all("noexec" in t for t in _pairs(args, "--tmpfs"))
    assert "--pid" not in args and "--ipc" not in args and "--userns" not in args
    assert _pairs(args, "--workdir") == [str(RUN / "backend")]


def test_host_path_is_only_the_mount_source():
    args = _args(host_run_dir=Path("/srv/data/projects/run-1"))
    assert _pairs(args, "--mount") == [f"type=bind,src=/srv/data/projects/run-1,dst={RUN}"]


def test_environment_is_passed_through_minus_host_path():
    envs = _pairs(_args(), "--env")
    assert "DATABASE_URL=sqlite:///x.db" in envs
    assert not any(e.startswith("PATH=") for e in envs)


def test_network_isolation():
    assert _pairs(_args(), "--network") == ["none"]
    assert "--publish" not in _args()
    app = _args(network=db.RUN_NETWORK, publish=("127.0.0.1", 41234), detach=True)
    assert _pairs(app, "--network") == [db.RUN_NETWORK]
    assert _pairs(app, "--publish") == ["127.0.0.1:41234:41234"]   # loopback only, never 0.0.0.0
    for bad in ("host", "bridge", "container:aether_os_api_1", "aether_os_default"):
        with pytest.raises(SandboxViolation):
            _args(network=bad)
    with pytest.raises(SandboxViolation):  # installs may not expose a port
        _args(network=db.EGRESS_NETWORK, publish=("127.0.0.1", 1))


def test_sandbox_networks_have_no_inter_container_traffic_and_app_net_no_masquerade():
    run = db.network_create_args(db.RUN_NETWORK)
    egress = db.network_create_args(db.EGRESS_NETWORK)
    assert "com.docker.network.bridge.enable_icc=false" in run
    assert "com.docker.network.bridge.enable_icc=false" in egress
    assert "com.docker.network.bridge.enable_ip_masquerade=false" in run
    assert "--internal" not in egress  # installs need the internet; the host firewall limits where


@pytest.mark.parametrize("bad", [
    dict(user="0:0"), dict(user="root"),
    dict(run_dir=Path("/")), dict(run_dir=Path("relative/run")),
    dict(cwd=Path("/etc")), dict(cwd=RUN.parent / "other-run"),
])
def test_bad_policy_is_refused(bad):
    with pytest.raises(SandboxViolation):
        _args(**bad)


def test_root_gateway_still_gets_a_non_root_container(monkeypatch):
    monkeypatch.delenv("AETHER_SANDBOX_UID", raising=False)
    monkeypatch.setattr(os, "getuid", lambda: 0)
    assert db.sandbox_user() == "10001:10001"


# ── selection: fail closed ────────────────────────────────────────────────────

@pytest.fixture
def clean_env(monkeypatch):
    for k in ("AETHER_SANDBOX", "AETHER_SANDBOX_ALLOW_NONE", "ENVIRONMENT"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_production_without_docker_refuses(clean_env):
    clean_env.setenv("ENVIRONMENT", "production")
    clean_env.setattr(db.DockerRunner, "available", lambda self: False)
    with pytest.raises(SandboxUnavailable):
        get_runner()


@pytest.mark.parametrize("choice", ["macos", "none"])
def test_production_allows_only_docker(clean_env, choice):
    clean_env.setenv("ENVIRONMENT", "production")
    clean_env.setenv("AETHER_SANDBOX", choice)
    clean_env.setenv("AETHER_SANDBOX_ALLOW_NONE", "1")
    with pytest.raises(SandboxUnavailable):
        get_runner()


def test_production_default_is_docker(clean_env):
    clean_env.setenv("ENVIRONMENT", "production")
    clean_env.setattr(db.DockerRunner, "available", lambda self: True)
    assert get_runner().name == "docker"


def test_none_needs_the_dev_flag_and_is_logged(clean_env, caplog):
    clean_env.setenv("AETHER_SANDBOX", "none")
    with pytest.raises(SandboxUnavailable):
        get_runner()
    clean_env.setenv("AETHER_SANDBOX_ALLOW_NONE", "1")
    assert get_runner().name == "none"
    assert any("SANDBOX DISABLED" in r.message for r in caplog.records)


def test_unknown_or_unavailable_backend_refuses(clean_env):
    clean_env.setenv("AETHER_SANDBOX", "chroot")
    with pytest.raises(SandboxUnavailable):
        get_runner()
    clean_env.setenv("AETHER_SANDBOX", "docker")
    clean_env.setattr(db.DockerRunner, "available", lambda self: False)
    with pytest.raises(SandboxUnavailable):   # no silent fallback to macos/none
        get_runner()


def test_output_is_capped_from_the_end():
    capped = rn.cap_output(b"a" * 100 + b"ERROR", 10)
    assert capped.endswith(b"aaaaaERROR") and len(capped) < 40


# ── live Docker (skipped without a daemon and the image) ─────────────────────

def _docker_ready() -> bool:
    try:
        return db.DockerRunner().available()
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _docker_ready(), reason="Docker daemon or aether-sandbox image not available")
def test_live_container_cannot_see_host_files_or_platform(tmp_path):
    runner = db.DockerRunner(Limits(timeout_s=60))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "ok.txt").write_text("ok")
    script = ("import os,socket\n"
              "print(open('ok.txt').read())\n"
              f"print(os.path.exists({str(Path.home())!r}))\n"
              "s=socket.socket(); s.settimeout(2)\n"
              "try:\n s.connect(('1.1.1.1',53)); print('NET')\n"
              "except OSError: print('NONET')\n"
              "try:\n open('/etc/x','w'); print('ROOTFS-WRITABLE')\n"
              "except OSError: print('RO')\n")
    out = runner.run(["python3", "-c", script], run_dir=run_dir, env={}, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.decode().split() == ["ok", "False", "NONET", "RO"]
