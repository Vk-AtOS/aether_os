"""KAN-256: generated pytest runs in a venv that has the app's requirements (stripe/boto3 imports used to crash
collection on the base interpreter); KAN-245: the firewall systemd unit exists and is installed by the deploy scripts."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

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
        if "venv" in argv:
            py = Path(argv[-1]) / "bin" / "python"
            py.parent.mkdir(parents=True)
            py.touch()
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


def test_pytest_runs_in_venv_after_installing_requirements_with_network_only_for_pip(tmp_path, monkeypatch):
    runner = Runner()
    monkeypatch.setattr(phase_exec, "get_runner", lambda *a, **k: runner)
    monkeypatch.setattr(phase_exec, "project_root", lambda p: tmp_path)
    backend = _project(tmp_path)
    phase_exec.run_sync(["python3", "-m", "pytest", "tests"], cwd=backend, project=tmp_path)
    pip = [c for c in runner.calls if "pip" in c.argv]
    assert pip and pip[0].network is True and "-r" in pip[0].argv
    last = runner.calls[-1]
    assert last.argv[0].endswith(".venv-fake/bin/python") and last.network is False
    n = len(runner.calls)
    phase_exec.run_sync(["python3", "-m", "pytest", "tests"], cwd=backend, project=tmp_path)
    assert len(runner.calls) == n + 1                       # second run: no reinstall (same requirements hash)


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


def test_pip_runs_isolated_with_a_minimal_env_binary_only_and_outside_the_project(tmp_path, monkeypatch):
    runner = Runner()
    monkeypatch.setattr(phase_exec, "get_runner", lambda *a, **k: runner)
    monkeypatch.setattr(phase_exec, "project_root", lambda p: tmp_path)
    backend = _project(tmp_path)
    phase_exec.run_sync(["python3", "-m", "pytest"], cwd=backend, project=tmp_path,
                        env={"PYTHONPATH": str(backend), "PYTHONSTARTUP": "x", "SECRET": "s"})
    pip = next(c for c in runner.calls if "pip" in c.argv)
    assert "-I" in pip.argv and "--only-binary=:all:" in pip.argv
    assert not [k for k in pip.env if k.startswith("PYTHON") or k == "SECRET"]
    assert Path(pip.cwd) == tmp_path / ".sandbox_home"


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


def test_marker_lives_outside_the_sandbox_writable_tree_so_a_symlink_cannot_redirect_it(tmp_path, monkeypatch, host_state):
    runner = Runner()
    monkeypatch.setattr(phase_exec, "get_runner", lambda *a, **k: runner)
    monkeypatch.setattr(phase_exec, "project_root", lambda p: tmp_path)
    backend = _project(tmp_path)
    victim = tmp_path.parent / "victim"
    # the sandbox pre-plants a symlink where the old marker would have been created
    (tmp_path / ".venv-fake").mkdir()
    (tmp_path / ".venv-fake" / ".reqs-x").symlink_to(victim)
    phase_exec.run_sync(["python3", "-m", "pytest"], cwd=backend, project=tmp_path)
    assert not victim.exists()
    assert [p.name for p in host_state.iterdir() if p.name.startswith("reqs-")]
    assert not [p for p in (tmp_path / ".venv-fake").iterdir() if p.name != ".reqs-x" and p.name.startswith(".reqs-")]
