"""KAN-66: the Docker sandbox backend against a real daemon. Skipped unless the daemon is up and `aether-sandbox:1` is built:

    docker build -f core/sandbox/Dockerfile -t aether-sandbox:1 core/sandbox
    PYTHONPATH=<parent of aether_os> python3.11 -m pytest -q -m docker tests/test_docker_sandbox_live.py

Covers a generated app's life (build step, run, published preview port, teardown) and the policy the backend promises:
resource limits, no network for builds, read-only root, non-root user, cleanup after a crash. It has NOT been run in
the environment this was written in (the Docker daemon was not running); treat the first run on a Docker host as the
real verification and file a bug per failure.
"""
import os
import socket
import subprocess
import time
import urllib.request
import uuid

import pytest

import aether_os.core.sandbox.docker_backend as db
from aether_os.core.sandbox.runner import Limits


def _ready() -> bool:
    try:
        return db.DockerRunner().available()
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = [pytest.mark.docker, pytest.mark.skipif(not _ready(), reason="Docker daemon or aether-sandbox image not available")]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "runs" / "r1"
    d.mkdir(parents=True)
    d.chmod(0o777)            # the container user is not the test's owner on every host
    return d


def _py(runner, run_dir, code, *, network=False, timeout=60):
    return runner.run(["python3", "-c", code], run_dir=run_dir, env={}, timeout=timeout, network=network)


def test_container_runs_as_a_non_root_user_with_a_read_only_root(run_dir):
    out = _py(db.DockerRunner(Limits(timeout_s=60)), run_dir,
              "import os;print(os.getuid());\ntry:\n open('/usr/x','w')\nexcept OSError: print('RO')")
    assert out.returncode == 0, out.stderr
    uid, ro = out.stdout.decode().split()
    assert uid != "0" and ro == "RO"


def test_build_steps_have_no_network(run_dir):
    code = ("import socket\ns=socket.socket();s.settimeout(3)\n"
            "try:\n s.connect(('1.1.1.1',53));print('NET')\nexcept OSError:print('NONET')")
    assert _py(db.DockerRunner(Limits(timeout_s=60)), run_dir, code).stdout.decode().strip() == "NONET"


def test_memory_limit_kills_a_runaway_command(run_dir):
    out = _py(db.DockerRunner(Limits(timeout_s=60, memory_mb=128)), run_dir, "x=bytearray(1024*1024*1024);print('ALLOCATED')")
    assert b"ALLOCATED" not in out.stdout and out.returncode != 0          # OOM-killed, not allowed to take the host's RAM


def test_pids_limit_stops_a_fork_bomb(run_dir):
    code = ("import os\nn=0\n"
            "try:\n  [os.fork() for _ in range(5000)]\nexcept OSError:\n  print('LIMITED')")
    out = _py(db.DockerRunner(Limits(timeout_s=60, pids=64)), run_dir, code)
    assert b"LIMITED" in out.stdout or out.returncode != 0


def test_timeout_removes_the_container(run_dir):
    runner = db.DockerRunner(Limits(timeout_s=60))
    before = subprocess.run(["docker", "ps", "-q", "--filter", "name=aether-sbx-"], capture_output=True, text=True).stdout.split()
    with pytest.raises(subprocess.TimeoutExpired):
        runner.run(["python3", "-c", "import time;time.sleep(60)"], run_dir=run_dir, env={}, timeout=3)
    time.sleep(1)
    after = subprocess.run(["docker", "ps", "-q", "--filter", "name=aether-sbx-"], capture_output=True, text=True).stdout.split()
    assert set(after) <= set(before)                                       # nothing left running after the timeout


def test_app_lifecycle_start_preview_port_and_teardown(run_dir):
    (run_dir / "index.html").write_text("hello from the sandbox")
    runner = db.DockerRunner(Limits(timeout_s=60))
    port, nonce = _free_port(), uuid.uuid4().hex
    log = run_dir / "app.log"
    proc = runner.start(["python3", "-m", "http.server", str(port), "--bind", "0.0.0.0"], run_dir=run_dir, cwd=run_dir,
                        env={}, log_path=log, port=port, labels=db.labels_for("r1", nonce))
    try:
        body = None
        for _ in range(40):
            try:
                body = urllib.request.urlopen(f"http://{db.publish_ip()}:{port}/index.html", timeout=2).read()
                break
            except OSError:
                time.sleep(0.5)
        assert body == b"hello from the sandbox"                          # published only on AETHER_SANDBOX_PUBLISH_IP
        assert proc.poll() is None and db.is_launched_container(proc.container_id, nonce)
        assert not db.is_launched_container(proc.container_id, "x" * 32)   # another launch's nonce is refused
    finally:
        proc.terminate()
    for _ in range(20):
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    assert proc.poll() is not None                                         # torn down


def test_a_crashed_gateway_leaves_a_container_that_is_found_by_label_and_removed(run_dir):
    runner = db.DockerRunner(Limits(timeout_s=60))
    port, nonce = _free_port(), uuid.uuid4().hex
    proc = runner.start(["python3", "-m", "http.server", str(port), "--bind", "0.0.0.0"], run_dir=run_dir, cwd=run_dir,
                        env={}, log_path=run_dir / "app.log", port=port, labels=db.labels_for("crashed", nonce))
    try:
        found = subprocess.run(["docker", "ps", "-q", "--filter", f"label={db.LABEL_RUN}=crashed"],
                               capture_output=True, text=True).stdout.split()
        assert found, "a container started by a gateway that then died must be findable by its run label"
    finally:
        db.remove_container(proc.container_id)
    assert not db.is_launched_container(proc.container_id, nonce)


def test_published_port_is_not_on_all_interfaces():
    assert db.publish_ip() == os.environ.get("AETHER_SANDBOX_PUBLISH_IP", "127.0.0.1") and db.publish_ip() != "0.0.0.0"
