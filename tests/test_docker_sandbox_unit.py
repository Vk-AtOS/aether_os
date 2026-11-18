"""KAN-66: defects found by reading docker_backend.py against what the run-app code expects (no Docker needed)."""
import subprocess
from pathlib import Path

import aether_os.core.sandbox.docker_backend as db

ROOT = Path(__file__).resolve().parents[1]


def _fake_docker(monkeypatch, answers):
    """answers: {first docker arg: (returncode, stdout)}"""
    calls = []

    def fake(*args, timeout=30):
        calls.append(args)
        rc, out = answers.get(args[0], (0, ""))
        return subprocess.CompletedProcess(args, rc, out, "")
    monkeypatch.setattr(db, "_docker", fake)
    return calls


def test_wait_returns_the_containers_real_exit_code(monkeypatch):
    # root cause: wait() discarded `docker wait`'s output and reported 0 for a container that crashed with 1
    _fake_docker(monkeypatch, {"wait": (0, "1\n")})
    p = db.ContainerProcess("abc")
    assert p.wait(5) == 1 and p.returncode == 1


def test_poll_reports_the_exit_code_of_a_stopped_container(monkeypatch):
    # root cause: poll() answered -1 for every stopped container, so a clean exit (0) looked like a crash
    _fake_docker(monkeypatch, {"inspect": (0, "false 0\n")})
    assert db.ContainerProcess("abc").poll() == 0
    _fake_docker(monkeypatch, {"inspect": (0, "false 137\n")})
    assert db.ContainerProcess("abc").poll() == 137
    _fake_docker(monkeypatch, {"inspect": (0, "true 0\n")})
    assert db.ContainerProcess("abc").poll() is None                    # still running
    _fake_docker(monkeypatch, {"inspect": (1, "")})
    assert db.ContainerProcess("gone").poll() == -1                     # no such container


def test_api_image_has_the_docker_cli_the_backend_shells_out_to():
    # root cause: the compose file mounts docker.sock into the API container and sets AETHER_SANDBOX=docker, but the
    # image never installed `docker`, so every sandboxed command failed with FileNotFoundError in the shipped stack
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "COPY --from=docker:" in dockerfile and "/usr/local/bin/docker" in dockerfile
    assert db.DOCKER == "docker"
