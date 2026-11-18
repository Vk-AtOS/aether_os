"""KAN-99 / KAN-65: a generated Dockerfile is built in the builder sandbox (kaniko), never by the host daemon.
The live build needs a Docker daemon and the images:

    docker build -f core/sandbox/Dockerfile -t aether-sandbox:1 core/sandbox
    docker build -f core/sandbox/Dockerfile.builder -t aether-builder:1 core/sandbox
"""
import asyncio
import subprocess
from pathlib import Path

import pytest

from aether_os.core.errors import SandboxViolation
from aether_os.core.sandbox import build_runner as br
from aether_os.core.sandbox.runner import Limits, SandboxUnavailable
from aether_os.phases.p11_deployment import helpers


def _args(tmp_path, **kw):
    run = tmp_path / "runs" / "r1"
    base = dict(name="n", run_dir=run, context=run / "app", tar_path=run / ".sandbox_tmp/x.tar", tag="img",
                limits=Limits(), img="aether-builder:1")
    base.update(kw)
    return br.builder_args(**base)


def test_policy_of_the_build_container(tmp_path):
    a = _args(tmp_path)
    s = " ".join(a)
    assert "/var/run/docker.sock" not in s and "--privileged" not in a and "--pid" not in a and "--net=host" not in a
    assert a[a.index("--cap-drop") + 1] == "ALL" and "no-new-privileges" in s
    assert a[a.index("--network") + 1] == "aether-sbx-egress"          # the firewalled egress bridge, never host
    mounts = [x for x in a if x.startswith("type=bind")]
    assert len(mounts) == 1 and mounts[0].startswith(f"type=bind,src={tmp_path / 'runs' / 'r1'},dst=")
    assert "--no-push" in a and "--tar-path" in a
    assert {a[i + 1] for i, x in enumerate(a) if x == "--cap-add"} == set(br.KANIKO_CAPS)


@pytest.mark.parametrize("bad", [
    {"context": Path("/etc")}, {"tar_path": Path("/tmp/x.tar")}, {"tag": "a;rm -rf /"}, {"tag": ""},
    {"run_dir": Path("/tmp")},
])
def test_paths_outside_the_run_dir_and_odd_tags_are_refused(tmp_path, bad):
    with pytest.raises(SandboxViolation):
        _args(tmp_path, **bad)


def test_no_builder_means_no_build_and_no_host_docker_build(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(br.DockerRunner, "available", lambda self: False)
    monkeypatch.setattr(br.subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(SandboxUnavailable):
        br.build_image(tmp_path / "app", "img", run_dir=tmp_path)
    assert calls == []
    monkeypatch.setattr(br.DockerRunner, "available", lambda self: True)
    monkeypatch.setattr(br, "_docker", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
    with pytest.raises(SandboxUnavailable) as ei:
        br.build_image(tmp_path / "app", "img", run_dir=tmp_path)
    assert "not built" in str(ei.value)


def test_successful_build_loads_the_tar_and_cleans_up(tmp_path, monkeypatch):
    app = tmp_path / "runs" / "r1" / "app"
    app.mkdir(parents=True)
    seen = {"docker": []}
    monkeypatch.setattr(br.DockerRunner, "available", lambda self: True)

    def fake_docker(*a, **k):
        seen["docker"].append(a)
        return subprocess.CompletedProcess(a, 0, "", "")

    def fake_run(args, **k):
        Path(args[args.index("--tar-path") + 1]).write_bytes(b"tar")
        seen["run"] = args
        return subprocess.CompletedProcess(args, 0, b"", b"")
    monkeypatch.setattr(br, "_docker", fake_docker)
    monkeypatch.setattr(br.subprocess, "run", fake_run)
    done = br.build_image(app, "aetheros-abc", run_dir=app.parent)
    assert done.returncode == 0
    assert any(c[0] == "load" for c in seen["docker"])
    assert not (app.parent / ".sandbox_tmp" / "aetheros-abc.tar").exists()
    assert "build" not in seen["run"][:3]                              # `docker run ... kaniko`, not `docker build`


def test_p11_docker_build_goes_through_the_builder_and_reports_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers.phase_exec, "project_root", lambda p: tmp_path)

    def refuse(*a, **k):
        raise SandboxUnavailable("no docker")
    monkeypatch.setattr(helpers, "build_image", refuse)
    out = asyncio.run(helpers.docker_build(tmp_path, "img"))
    assert out["success"] is False and "builder sandbox unavailable" in out["error"]

    monkeypatch.setattr(helpers, "build_image",
                        lambda *a, **k: subprocess.CompletedProcess([], 1, b"", b"step 3 failed"))
    out = asyncio.run(helpers.docker_build(tmp_path, "img"))
    assert out["success"] is False and "step 3 failed" in out["error"]
    monkeypatch.setattr(helpers, "build_image", lambda *a, **k: subprocess.CompletedProcess([], 0, b"", b""))
    assert asyncio.run(helpers.docker_build(tmp_path, "img")) == {"success": True}


def test_helpers_has_no_host_docker_build_left():
    src = Path(helpers.__file__).read_text()
    assert '"docker", "build"' not in src


def _live() -> bool:
    try:
        return br.DockerRunner().available() and br._docker("image", "inspect", br.builder_image()).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.docker
@pytest.mark.skipif(not _live(), reason="Docker daemon, sandbox image or aether-builder image not available")
def test_live_build_of_a_tiny_dockerfile(tmp_path):
    run = tmp_path / "runs" / "r1"
    app = run / "app"
    app.mkdir(parents=True)
    run.chmod(0o777)
    (app / "Dockerfile").write_text("FROM scratch\nCOPY hello /hello\n")
    (app / "hello").write_text("hi")
    done = br.build_image(app, "aether-build-live-test", run_dir=run, timeout=300)
    assert done.returncode == 0, done.stderr
    assert br._docker("image", "inspect", "aether-build-live-test").returncode == 0
    br._docker("rmi", "-f", "aether-build-live-test")
