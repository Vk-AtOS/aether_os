"""KAN-99 / KAN-65: browser jobs run through the sandbox runner ("browser" profile), fail closed, stay inside the run dir.
The live run needs a Docker daemon and the aether-sandbox-browser image:

    docker build -f core/sandbox/Dockerfile -t aether-sandbox:1 core/sandbox
    docker build -f core/sandbox/Dockerfile.browser -t aether-sandbox-browser:1 core/sandbox
"""
import json
import subprocess

import pytest

from aether_os.core.sandbox import browser_job, docker_backend, runner as runner_mod
from aether_os.core.sandbox.runner import SandboxUnavailable


class FakeRunner(runner_mod.SandboxRunner):
    name = "docker"

    def __init__(self, reply):
        super().__init__()
        self.reply, self.calls = reply, []

    def available(self):
        return True

    def base_python(self):
        return "python3"

    def browser_entry(self):
        return docker_backend.BROWSER_ENTRY_IN_IMAGE

    def run(self, argv, *, run_dir, cwd=None, env, timeout=None, network=False):
        job = json.loads((run_dir / ".sandbox_tmp" / argv[2].split("/")[-1]).read_text())
        self.calls.append((list(argv), network, job))
        return subprocess.CompletedProcess(argv, 0, self.reply, b"")


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_job, "project_root", lambda p: tmp_path)
    return tmp_path


def test_job_runs_in_the_browser_profile_without_network(root, monkeypatch):
    fake = FakeRunner(b'noise\n{"ok": true, "violations": 0}\n')
    seen = {}
    monkeypatch.setattr(browser_job, "get_runner", lambda limits=None, profile="default": seen.update(p=profile) or fake)
    out = browser_job.run_browser_job_sync({"action": "axe", "out": str(root / "o.json")}, project=root)
    assert out == {"ok": True, "violations": 0} and seen["p"] == "browser"
    argv, network, job = fake.calls[0]
    assert argv[:2] == ["python3", docker_backend.BROWSER_ENTRY_IN_IMAGE] and network is False
    assert job["action"] == "axe"
    assert not list((root / ".sandbox_tmp").glob("browser_job_*.json"))      # the job file is removed


def test_paths_outside_the_run_dir_are_refused(root, monkeypatch):
    monkeypatch.setattr(browser_job, "get_runner", lambda limits=None, profile="default": FakeRunner(b"{}"))
    for bad in ({"action": "axe", "out": "/etc/x"}, {"action": "x", "serve": {"dir": "/etc", "port": 1}},
                {"action": "x", "backend": {"cwd": "/tmp", "port": 1, "argv": []}}):
        with pytest.raises(SandboxUnavailable):
            browser_job.run_browser_job_sync(bad, project=root)


def test_no_sandbox_means_the_page_is_never_opened(root, monkeypatch):
    def none(limits=None, profile="default"):
        raise SandboxUnavailable("no docker")
    monkeypatch.setattr(browser_job, "get_runner", none)
    with pytest.raises(SandboxUnavailable) as ei:
        browser_job.run_browser_job_sync({"action": "axe"}, project=root)
    assert "browser sandbox unavailable" in str(ei.value)


def test_unparsable_output_is_a_failed_job_not_a_pass():
    done = subprocess.CompletedProcess([], 3, b"Traceback...\n", b"boom")
    res = browser_job.parse_result(done)
    assert res["ok"] is False and "exited 3" in res["error"]


def test_docker_profile_selects_the_browser_image(monkeypatch):
    monkeypatch.setenv("AETHER_SANDBOX", "docker")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(docker_backend.DockerRunner, "available", lambda self: True)
    r = runner_mod.get_runner(profile="browser")
    assert r._img == docker_backend.browser_image() and r.browser_entry() == docker_backend.BROWSER_ENTRY_IN_IMAGE
    assert runner_mod.get_runner()._img == docker_backend.image()
    with pytest.raises(SandboxUnavailable):
        runner_mod.get_runner(profile="nonsense")


def _live() -> bool:
    try:
        return docker_backend.DockerRunner(img=docker_backend.browser_image()).available()
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.docker
@pytest.mark.skipif(not _live(), reason="Docker daemon or the aether-sandbox-browser image is not available")
def test_live_axe_and_screenshot_in_the_browser_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_SANDBOX", "docker")
    root = tmp_path / "runs" / "r1"
    dist = root / "dist"
    dist.mkdir(parents=True)
    root.chmod(0o777)
    dist.chmod(0o777)
    (dist / "index.html").write_text("<html lang='en'><title>t</title><main><h1>x</h1><img src='a.png'></main></html>")
    monkeypatch.setattr(browser_job, "project_root", lambda p: root)
    tmp = root / ".sandbox_tmp"
    tmp.mkdir()
    tmp.chmod(0o777)
    got = browser_job.run_browser_job_sync(
        {"action": "axe", "out": str(tmp / "axe.json"), "serve": {"dir": str(dist), "port": 4173},
         "url": "http://127.0.0.1:4173/"}, project=root, timeout=120)
    assert got["ok"] and got["violations"] >= 1          # the <img> has no alt text
    shot = browser_job.run_browser_job_sync(
        {"action": "screenshot", "out": str(tmp / "s.png"), "serve": {"dir": str(dist), "port": 4173},
         "url": "http://127.0.0.1:4173/"}, project=root, timeout=120)
    assert shot["ok"] and (tmp / "s.png").stat().st_size > 100


def _entry():
    import importlib.util
    import pathlib
    path = pathlib.Path(runner_mod.__file__).parent / "browser" / "entry.py"
    spec = importlib.util.spec_from_file_location("aether_browser_entry", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_driver_serves_the_build_on_loopback_under_its_base_path(tmp_path):
    import socket
    import urllib.request
    entry = _entry()
    (tmp_path / "index.html").write_text("hello-dist")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = entry.serve_static(str(tmp_path), port, "preview-base")
    try:
        assert entry.wait_port(port, 5)
        assert srv.server_address[0] == "127.0.0.1"
        for path in ("/", "/preview-base/"):
            assert urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5).read() == b"hello-dist"
    finally:
        srv.shutdown()


def test_driver_reports_a_failed_job_as_json_not_a_crash(tmp_path, capsys):
    entry = _entry()
    job = tmp_path / "j.json"
    job.write_text(json.dumps({"action": "nope"}))
    assert entry.main(["x", str(job)]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_the_driver_copy_never_writes_through_a_planted_symlink(root, monkeypatch, tmp_path):
    """Host backends copy the driver into the run dir. A fixed filename let a symlink planted there redirect the copy over any
    file the process can write; the copy now has a random name and goes through safe_fs (O_NOFOLLOW, exclusive)."""
    victim = tmp_path.parent / f"{tmp_path.name}_victim.py"
    victim.write_text("# do not overwrite\n")
    driver = tmp_path / "driver_src.py"
    driver.write_text("print('driver')\n")
    tmpdir = root / ".sandbox_tmp"
    tmpdir.mkdir(exist_ok=True)
    (tmpdir / "browser_entry.py").symlink_to(victim)                            # the old fixed name

    class HostRunner(FakeRunner):
        name = "host"

        def browser_entry(self):
            return str(driver)

        def run(self, argv, *, run_dir, cwd=None, env, timeout=None, network=False):
            self.calls.append((list(argv), network, None))
            assert (run_dir / ".sandbox_tmp" / argv[1].split("/")[-1]).read_text() == "print('driver')\n"
            return subprocess.CompletedProcess(argv, 0, b'{"ok": true}\n', b"")

    host = HostRunner(b"")
    monkeypatch.setattr(browser_job, "get_runner", lambda limits=None, profile="default": host)
    out = browser_job.run_browser_job_sync({"action": "axe", "out": str(root / "o.json")}, project=root)
    assert out == {"ok": True}
    assert victim.read_text() == "# do not overwrite\n"                         # nothing was written through the link
    assert not list(tmpdir.glob("browser_entry_*.py"))                          # and the copy is removed afterwards
    victim.unlink()
