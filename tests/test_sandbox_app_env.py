"""KAN-256: generated pytest runs in a venv that has the app's requirements (stripe/boto3 imports used to crash
collection on the base interpreter); KAN-245: the firewall systemd unit exists and is installed by the deploy scripts."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

from aether_os.core.sandbox import app_env, phase_exec
from aether_os.core.sandbox.runner import SandboxRunner

ROOT = Path(__file__).resolve().parent.parent


class Runner(SandboxRunner):
    name = "fake"

    def __init__(self, pip_rc=0):
        super().__init__()
        self.calls, self.pip_rc = [], pip_rc

    def available(self):
        return True

    def run(self, argv, *, run_dir, cwd=None, env, timeout=None, network=False):
        self.calls.append(SimpleNamespace(argv=list(argv), network=network))
        if "venv" in argv:
            py = Path(argv[-1]) / "bin" / "python"
            py.parent.mkdir(parents=True)
            py.touch()
        rc = self.pip_rc if "pip" in argv else 0
        return subprocess.CompletedProcess(argv, rc, b"", b"ERROR: No matching distribution found for stripe-x" if rc else b"")


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


def test_failed_install_falls_back_to_base_python_so_pytest_names_the_missing_module(tmp_path, monkeypatch, caplog):
    runner = Runner(pip_rc=1)
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
