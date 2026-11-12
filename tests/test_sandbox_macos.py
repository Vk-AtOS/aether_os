"""macOS development sandbox, exercised for real with sandbox-exec on this machine.

A process started through MacSandboxRunner must not read a file in the user's
home outside its run dir, must not connect to the local Postgres port (TCP or
its Unix socket), and must not write outside the run dir — while the same
commands without the sandbox succeed (so the test proves the sandbox, not the setup).
"""
from __future__ import annotations

import errno
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from aether_os.core.run_app.child_env import child_env
from aether_os.core.sandbox.macos_backend import MacSandboxRunner, macos_profile
from aether_os.core.sandbox.runner import Limits, sandbox_dirs

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS sandbox-exec only")

PROBE = r"""
import errno, json, socket, sys
out = {}
try:
    open(sys.argv[1]).read(); out["home_read"] = "allowed"
except OSError as e:
    out["home_read"] = e.errno
for port in (5432, 6379):
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect(("127.0.0.1", port)); out[str(port)] = "connected"
    except OSError as e:
        out[str(port)] = e.errno
u = socket.socket(socket.AF_UNIX)
try:
    u.connect("/tmp/.s.PGSQL.5432"); out["pg_socket"] = "connected"
except OSError as e:
    out["pg_socket"] = e.errno
try:
    open(sys.argv[2], "w").write("x"); out["home_write"] = "allowed"
except OSError as e:
    out["home_write"] = e.errno
out["run_read"] = open("inside.txt").read()
print(json.dumps(out))
"""


@pytest.fixture
def secret_in_home():
    path = Path.home() / ".aether_os" / f"sandbox_test_secret_{uuid.uuid4().hex}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("platform secret")
    target = path.with_name(path.name + "_written")
    yield path, target
    path.unlink(missing_ok=True)
    target.unlink(missing_ok=True)


@pytest.fixture
def runner():
    r = MacSandboxRunner(Limits(timeout_s=60))
    if not r.available():
        pytest.skip("sandbox-exec not usable here")
    return r


def test_sandboxed_process_cannot_read_home_or_reach_postgres(runner, tmp_path, secret_in_home):
    secret, target = secret_in_home
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "inside.txt").write_text("run dir ok")
    argv = [sys.executable, "-c", PROBE, str(secret), str(target)]
    env = child_env(**sandbox_dirs(run_dir))

    out = runner.run(argv, run_dir=run_dir, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout)
    assert res["run_read"] == "run dir ok"                       # its own run dir works
    assert res["home_read"] in (errno.EPERM, errno.EACCES)       # the home file does not
    assert res["home_write"] in (errno.EPERM, errno.EACCES)
    assert res["5432"] == errno.EPERM                             # blocked by the sandbox, not "refused"
    assert res["6379"] == errno.EPERM
    assert res["pg_socket"] in (errno.EPERM, errno.EACCES)
    assert not target.exists()

    # Control: the same probe outside the sandbox can read the file (the test is not vacuous).
    plain = subprocess.run(argv, cwd=run_dir, env=env, capture_output=True, timeout=60)
    assert json.loads(plain.stdout)["home_read"] == "allowed"


def test_long_running_app_is_sandboxed_too(runner, tmp_path, secret_in_home):
    secret, _ = secret_in_home
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    log = run_dir / "app.log"
    proc = runner.start([sys.executable, "-c", f"open({str(secret)!r}).read()"], run_dir=run_dir,
                        cwd=run_dir, env=child_env(**sandbox_dirs(run_dir)), log_path=log,
                        port=0, labels={})
    assert proc.wait(timeout=30) != 0
    assert "Operation not permitted" in log.read_text()


def test_profile_allows_only_the_run_dir():
    profile = macos_profile(Path("/private/var/folders/x/run-1"))
    assert '(deny file-read-data (subpath "/Users"))' in profile
    assert '(allow file-read-data (subpath "/private/var/folders/x/run-1"))' in profile
    assert '(deny file-write* (subpath "/"))' in profile
    assert '(deny network-outbound (remote ip "localhost:*"))' in profile
    # A hostile path cannot break out of its string literal.
    assert '\\"' in macos_profile(Path('/private/var/folders/x/a"b'))
