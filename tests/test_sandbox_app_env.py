"""KAN-256: generated pytest runs in a venv that has the app's requirements (stripe/boto3 imports used to crash
collection on the base interpreter); KAN-245: the firewall systemd unit exists and is installed by the deploy scripts."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import shutil

import pytest

from aether_os.core.sandbox import app_env, phase_exec
from aether_os.core.sandbox.runner import SandboxRunner

ROOT = Path(__file__).resolve().parent.parent


class Runner(SandboxRunner):
    name = "fake"

    def __init__(self, pip_rc=0, wheel_error=True):
        super().__init__()
        self.calls, self.pip_rc, self.wheel_error = [], pip_rc, wheel_error

    def available(self):
        return True

    def run(self, argv, *, run_dir, cwd=None, env, timeout=None, network=False):
        self.calls.append(SimpleNamespace(argv=list(argv), network=network, env=dict(env), cwd=cwd))
        if "pip" in argv and self.pip_rc == 0:
            (Path(argv[argv.index("--target") + 1]) / "stripe").mkdir(parents=True)
        rc = self.pip_rc if "pip" in argv else 0
        return subprocess.CompletedProcess(argv, rc, b"", (b"ERROR: No matching distribution found for stripe-x" if self.wheel_error else b"network down stripe-x") if rc else b"")


@pytest.fixture(autouse=True)
def host_state(tmp_path, monkeypatch):
    state = tmp_path.parent / (tmp_path.name + "-state")
    state.mkdir()
    monkeypatch.setattr(app_env, "state_dir", lambda run_id: state)
    return state


def _project(tmp_path):
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    (tmp_path / "backend" / "requirements.txt").write_text("stripe\nboto3\n")
    return tmp_path / "backend"


def test_pytest_gets_the_installed_packages_on_pythonpath_and_network_is_only_for_pip(tmp_path, monkeypatch):
    runner = Runner()
    monkeypatch.setattr(phase_exec, "get_runner", lambda *a, **k: runner)
    monkeypatch.setattr(phase_exec, "project_root", lambda p: tmp_path)
    backend = _project(tmp_path)
    phase_exec.run_sync(["python3", "-m", "pytest", "tests"], cwd=backend, project=tmp_path, env={"PYTHONPATH": str(backend)})
    pip = [c for c in runner.calls if "pip" in c.argv]
    assert len(pip) == 1 and pip[0].network is True
    last = runner.calls[-1]
    assert last.network is False and last.argv[0] == runner.base_python()
    deps = [p for p in last.env["PYTHONPATH"].split(":") if ".deps-" in p]
    assert deps and (Path(deps[0]) / "stripe").is_dir() and str(backend) in last.env["PYTHONPATH"]
    n = len(runner.calls)
    phase_exec.run_sync(["python3", "-m", "pytest", "tests"], cwd=backend, project=tmp_path)
    assert len(runner.calls) == n + 1                       # second run: no reinstall (same requirements)
    assert not list(tmp_path.glob(".pipwork-*"))             # scratch dirs removed


def test_failed_install_without_a_wheel_fails_naming_the_package(tmp_path, monkeypatch):
    runner = Runner(pip_rc=1)
    monkeypatch.setattr(phase_exec, "get_runner", lambda *a, **k: runner)
    monkeypatch.setattr(phase_exec, "project_root", lambda p: tmp_path)
    with pytest.raises(app_env.RequirementsRejected, match="stripe-x"):
        phase_exec.run_sync(["python3", "-m", "pytest"], cwd=_project(tmp_path), project=tmp_path)


def test_failed_install_falls_back_to_base_python_so_pytest_names_the_missing_module(tmp_path, monkeypatch, caplog):
    runner = Runner(pip_rc=1, wheel_error=False)
    monkeypatch.setattr(phase_exec, "get_runner", lambda *a, **k: runner)
    monkeypatch.setattr(phase_exec, "project_root", lambda p: tmp_path)
    backend = _project(tmp_path)
    phase_exec.run_sync(["python3", "-m", "pytest", "tests"], cwd=backend, project=tmp_path)
    assert runner.calls[-1].argv[0] == runner.base_python()
    assert "stripe-x" in caplog.text


def test_no_requirements_means_base_python_and_non_pytest_commands_are_untouched(tmp_path, monkeypatch):
    runner = Runner()
    monkeypatch.setattr(phase_exec, "get_runner", lambda *a, **k: runner)
    monkeypatch.setattr(phase_exec, "project_root", lambda p: tmp_path)
    backend = _project(tmp_path)
    (backend / "requirements.txt").unlink()
    phase_exec.run_sync(["python3", "-m", "pytest"], cwd=backend, project=tmp_path)
    phase_exec.run_sync(["python3", "-c", "pass"], cwd=backend, project=tmp_path)
    assert all(not c.network for c in runner.calls) and len(runner.calls) == 2
    assert app_env.is_pytest(["python3", "-m", "pytest", "x"]) and not app_env.is_pytest(["python3", "-c", "x"])


def test_firewall_unit_and_install_steps():
    unit = (ROOT / "deploy/systemd/aether-sandbox-firewall.service").read_text()
    assert "Type=oneshot" in unit
    assert "EnvironmentFile=/etc/aether/sandbox-firewall.env" in unit and "core/sandbox/host_firewall.sh" in unit
    assert "docker.service" in unit.split("After=")[1].split("\n")[0]
    for script in ("deploy/deploy.sh", "deploy/terraform/aws/environments/prod-single/bootstrap.sh"):
        assert "install_sandbox_firewall.sh" in (ROOT / script).read_text()
    assert "deploy/systemd/aether-sandbox-firewall.service" in (ROOT / "deploy/scripts/install_sandbox_firewall.sh").read_text()


def test_pip_argv_env_and_cwd_trust_nothing_in_the_run_dir(tmp_path, monkeypatch):
    runner = Runner()
    monkeypatch.setattr(phase_exec, "get_runner", lambda *a, **k: runner)
    monkeypatch.setattr(phase_exec, "project_root", lambda p: tmp_path)
    backend = _project(tmp_path)
    phase_exec.run_sync(["python3", "-m", "pytest"], cwd=backend, project=tmp_path,
                        env={"PYTHONPATH": str(backend), "PYTHONSTARTUP": "x", "SECRET": "s", "PIP_INDEX_URL": "http://evil"})
    pip = next(c for c in runner.calls if "pip" in c.argv)
    a = pip.argv
    assert a[:4] == [runner.base_python(), "-I", "-m", "pip"] and "--python" not in a and "-r" not in a
    assert "--only-binary=:all:" in a and "--no-cache-dir" in a and "--target" in a
    assert a[a.index("--index-url") + 1] == "https://pypi.org/simple"
    assert a[-2:] == ["stripe", "boto3"] and not any("requirements.txt" in x for x in a)   # validated strings, not a file
    assert not [k for k in pip.env if k.startswith("PYTHON") or k in ("SECRET", "PIP_INDEX_URL")]
    assert pip.env["PIP_CONFIG_FILE"] == "/dev/null" and pip.env["PIP_NO_INPUT"] == "1"
    assert pip.env["HOME"] == pip.env["XDG_CONFIG_HOME"] and "/.pipwork-" in pip.env["HOME"]
    assert "/.pipwork-" in str(pip.cwd) and str(backend) not in str(pip.cwd)


def test_requirements_are_read_once_so_a_swap_after_validation_changes_nothing(tmp_path, monkeypatch):
    runner = Runner()
    backend = _project(tmp_path)
    req = backend / "requirements.txt"
    real_run = runner.run

    def swap_then_run(argv, **kw):
        req.write_text("-e git+https://evil/x\n")           # the sandbox rewrites the file while pip "runs"
        return real_run(argv, **kw)

    runner.run = swap_then_run
    monkeypatch.setattr(phase_exec, "get_runner", lambda *a, **k: runner)
    monkeypatch.setattr(phase_exec, "project_root", lambda p: tmp_path)
    phase_exec.run_sync(["python3", "-m", "pytest"], cwd=backend, project=tmp_path)
    pip = next(c for c in runner.calls if "pip" in c.argv)
    assert pip.argv[-2:] == ["stripe", "boto3"]


@pytest.mark.parametrize("line", ["pkg @ file:///etc/passwd", "foo.whl", "foo-1.0.tar.gz", "foo.zip", "bar.tgz",
                                  "baz.tar.xz", "-x", "a b c", "pkg==", "[extra]"])
def test_more_rejections_use_packaging_and_name_rules(line):
    with pytest.raises(app_env.RequirementsRejected):
        app_env.validate_requirements(line + "\n")


@pytest.mark.parametrize("line", ["fastapi", "fastapi>=0.110,<1", "uvicorn[standard]==0.29.0", "pydantic ~= 2.0  # c",
                                  "pywin32; sys_platform == 'win32'", "# only a comment", ""])
def test_plain_requirements_are_accepted(line):
    app_env.validate_requirements(line + "\n")


@pytest.mark.parametrize("line", ["-e .", "-r other.txt", "-c c.txt", "--index-url http://evil/simple",
                                  "--extra-index-url https://x", "--find-links /tmp", "--trusted-host evil",
                                  "pkg @ https://evil/x.whl", "https://evil/x.tar.gz", "git+https://github.com/a/b",
                                  "./local", "/abs/path", "../up", "pkg; python_version>'3' @ x"])
def test_option_url_vcs_and_path_requirements_are_rejected_naming_the_line(line):
    with pytest.raises(app_env.RequirementsRejected, match="line 2"):
        app_env.validate_requirements("fastapi\n" + line + "\n")


def test_marker_is_host_only_and_a_planted_deps_symlink_is_replaced_not_followed(tmp_path, monkeypatch, host_state):
    runner = Runner()
    monkeypatch.setattr(phase_exec, "get_runner", lambda *a, **k: runner)
    monkeypatch.setattr(phase_exec, "project_root", lambda p: tmp_path)
    backend = _project(tmp_path)
    victim = tmp_path.parent / "victim"
    victim.mkdir()
    phase_exec.run_sync(["python3", "-m", "pytest"], cwd=backend, project=tmp_path)
    deps = next(tmp_path.glob(".deps-*"))
    marker = next(host_state.glob("reqs-*"))
    # the sandbox swaps the packages dir for a symlink: the marker alone is not trusted, so it is rebuilt
    shutil.rmtree(deps)
    deps.symlink_to(victim)
    phase_exec.run_sync(["python3", "-m", "pytest"], cwd=backend, project=tmp_path)
    assert not deps.is_symlink() and (deps / "stripe").is_dir() and not list(victim.iterdir())
    assert marker.exists() and not list(tmp_path.glob(".reqs-*"))


def test_argv_items_are_rebuilt_from_parsed_parts():
    got = app_env.parse_requirements("Uvicorn[Standard,uvloop]>=0.29, <1 \nSome_Pkg==1.*\nfoo~=2.0; python_version >= '3.9'\n")
    assert got == ["uvicorn[Standard,uvloop]<1,>=0.29", "some-pkg==1.*", "foo~=2.0; python_version >= \"3.9\""]


@pytest.mark.parametrize("line", ["foo===1.0", "foo==../../x", "foo==1.0/evil", "foo>=1.*", "a\\b", "foo[a/b]", "foo==1.0 ; extra == 'x/y'",
                                  "foo==not.a.version"])
def test_triple_equals_path_like_and_bad_versions_are_rejected(line):
    with pytest.raises(app_env.RequirementsRejected):
        app_env.parse_requirements(line + "\n")


def test_requirements_file_must_be_a_regular_file_inside_the_run_dir(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    ok = root / "requirements.txt"
    ok.write_text("fastapi\n")
    assert app_env.read_requirements_file(ok, root) == "fastapi\n"
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET-line\n")
    link = root / "link.txt"
    link.symlink_to(secret)
    with pytest.raises(app_env.RequirementsRejected) as e:
        app_env.read_requirements_file(link, root)
    assert "TOPSECRET" not in str(e.value)
    outside_dir = tmp_path / "other"
    outside_dir.mkdir()
    (outside_dir / "r.txt").write_text("x\n")
    with pytest.raises(app_env.RequirementsRejected):
        app_env.read_requirements_file(outside_dir / "r.txt", root)
    (root / "d.txt").mkdir()
    with pytest.raises(app_env.RequirementsRejected):
        app_env.read_requirements_file(root / "d.txt", root)
    big = root / "big.txt"
    big.write_text("a\n" * app_env.MAX_REQ_BYTES)
    with pytest.raises(app_env.RequirementsRejected, match="too large"):
        app_env.read_requirements_file(big, root)


def test_symlinked_intermediate_directory_is_not_followed(tmp_path):
    """The sandbox swaps backend/ for a symlink to a directory outside the run dir after the path was chosen."""
    root = tmp_path / "run"
    (root / "real").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "requirements.txt").write_text("TOPSECRET\n")
    (root / "backend").symlink_to(outside)
    with pytest.raises(app_env.RequirementsRejected) as e:
        app_env.read_requirements_file(root / "backend" / "requirements.txt", root)
    assert "TOPSECRET" not in str(e.value)
    # and discovery: a requirements.txt symlink is refused, a symlinked dir is simply not entered
    (root / "real" / "requirements.txt").symlink_to(outside / "requirements.txt")
    with pytest.raises(app_env.RequirementsRejected):
        app_env.find_requirements(root / "real", root)


def test_rejection_errors_never_echo_line_content():
    with pytest.raises(app_env.RequirementsRejected) as e:
        app_env.parse_requirements("fastapi\nSECRETPAYLOAD==../../etc\n")
    assert "line 2" in str(e.value) and "SECRETPAYLOAD" not in str(e.value)
