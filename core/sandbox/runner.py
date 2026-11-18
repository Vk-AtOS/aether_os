"""One way to run generated code: SandboxRunner, chosen by AETHER_SANDBOX.

Generated apps, their install/build steps, their tests and their probes are
untrusted code. Everything that runs them goes through get_runner(), which
returns one of:

  docker  one container per run (core/sandbox/docker_backend.py). Production default.
  macos   sandbox-exec process sandbox (core/sandbox/macos_backend.py). Development
          default on macOS; best effort, see that module for what it does NOT stop.
  none    plain host process with an allowlisted environment. Only when
          AETHER_SANDBOX_ALLOW_NONE=1 and never in production; logged loudly.

Fail closed: an unknown choice, a backend that is not available on this host,
or "none" without the dev flag raises SandboxUnavailable — callers refuse to
run the code. There is no silent fallback from one backend to another.

The run directory is the only writable place a sandboxed process gets, and it
is visible at the same absolute path inside the sandbox, so paths the launcher
writes into generated files and environment variables need no translation.
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from aether_os.core.errors import SandboxViolation
from aether_os.core.run_app.safe_fs import open_log_fd

logger = logging.getLogger(__name__)


class SandboxUnavailable(SandboxViolation):
    """The configured sandbox cannot run here; generated code must not run at all."""


@dataclass(frozen=True)
class Limits:
    memory_mb: int = 1536
    cpus: float = 1.0
    pids: int = 512
    timeout_s: int = 300           # one-shot commands (install, build, tests, probes)
    output_bytes: int = 256_000    # per stream, kept from the end
    file_bytes: int = 1 << 30      # largest single file a sandboxed process may write


def is_production() -> bool:
    return os.environ.get("ENVIRONMENT", "development") == "production"


def cap_output(data: Optional[bytes], limit: int) -> bytes:
    """Keep the last `limit` bytes: errors are at the end of build output."""
    data = data or b""
    return data if len(data) <= limit else b"[...truncated...]\n" + data[-limit:]


def sandbox_dirs(run_dir: Path) -> Dict[str, str]:
    """Per-run HOME and TMPDIR inside the run dir, so caches and temp files of one
    run are neither shared with the platform nor with other runs."""
    home, tmp = run_dir / ".sandbox_home", run_dir / ".sandbox_tmp"
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    return {"HOME": str(home), "TMPDIR": str(tmp)}


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError as exc:
        logger.warning("sandbox: could not kill process group %s: %s", proc.pid, exc)


class SandboxRunner:
    """Interface. `run` for one-shot commands, `start` for the long-running app.

    `run` returns a CompletedProcess with byte output capped to limits.output_bytes
    and raises subprocess.TimeoutExpired after killing everything it started.
    `start` returns a handle with the Popen surface the run-app code uses:
    pid, poll(), terminate(), kill(), wait(timeout).
    """

    name = "abstract"
    bind_host = "127.0.0.1"   # address the app must listen on inside the sandbox

    def __init__(self, limits: Limits = Limits()) -> None:
        self.limits = limits

    def available(self) -> bool:
        raise NotImplementedError

    def base_python(self) -> str:
        return sys.executable

    def tool(self, name: str) -> Optional[str]:
        """Path of a toolchain binary (npm, npx, node) as seen inside the sandbox."""
        return shutil.which(name)

    def browser_entry(self) -> str:
        """Path of the in-sandbox browser driver (core/sandbox/browser/entry.py) as the sandbox sees it."""
        return str(Path(__file__).resolve().parent / "browser" / "entry.py")

    def run(self, argv: Sequence[str], *, run_dir: Path, cwd: Optional[Path] = None,
            env: Mapping[str, str], timeout: Optional[int] = None,
            network: bool = False) -> subprocess.CompletedProcess:
        raise NotImplementedError

    def start(self, argv: Sequence[str], *, run_dir: Path, cwd: Path, env: Mapping[str, str],
              log_path: Path, port: int, labels: Mapping[str, str]):
        raise NotImplementedError

    # Shared host-process plumbing (used by the macos and none backends).
    def _host_run(self, argv: List[str], cwd: Path, env: Mapping[str, str], timeout: int,
                  preexec=None) -> subprocess.CompletedProcess:
        proc = subprocess.Popen(argv, cwd=str(cwd), env=dict(env), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True, preexec_fn=preexec)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)  # the whole session: npm and pip spawn children
            proc.communicate()
            raise
        return subprocess.CompletedProcess(argv, proc.returncode,
                                           cap_output(out, self.limits.output_bytes),
                                           cap_output(err, self.limits.output_bytes))


class NoSandboxRunner(SandboxRunner):
    """Plain host process: environment allowlist only. Development escape hatch."""

    name = "none"

    def available(self) -> bool:
        return True

    def run(self, argv, *, run_dir, cwd=None, env, timeout=None, network=False):
        return self._host_run(list(argv), cwd or run_dir, env, timeout or self.limits.timeout_s)

    def start(self, argv, *, run_dir, cwd, env, log_path, port, labels):
        # O_NOFOLLOW: the log sits in the run dir, where the app can plant a symlink.
        log = open_log_fd(log_path)
        try:
            return subprocess.Popen(list(argv), cwd=str(cwd), env=dict(env), stdout=log, stderr=log,
                                    start_new_session=True)
        finally:
            os.close(log)


def get_runner(limits: Limits = Limits(), profile: str = "default") -> SandboxRunner:
    """The configured runner, or SandboxUnavailable (fail closed). See module docstring.

    profile "browser": the docker backend uses the browser image (Chromium, Playwright, axe-core);
    the host backends (development only) use the host's own tools."""
    # Imported here: both backends import this module for the base class.
    from aether_os.core.sandbox.docker_backend import DockerRunner, browser_image
    from aether_os.core.sandbox.macos_backend import MacSandboxRunner

    if profile not in ("default", "browser"):
        raise SandboxUnavailable(f"unknown sandbox profile {profile!r}")

    prod = is_production()
    default = "docker" if prod or sys.platform != "darwin" else "macos"
    choice = (os.environ.get("AETHER_SANDBOX") or default).strip().lower()
    if prod and choice != "docker":
        raise SandboxUnavailable(f"AETHER_SANDBOX={choice!r} is not allowed in production; only docker")
    if choice == "none":
        if os.environ.get("AETHER_SANDBOX_ALLOW_NONE") != "1":
            raise SandboxUnavailable("AETHER_SANDBOX=none needs AETHER_SANDBOX_ALLOW_NONE=1 (development only)")
        logger.error("SANDBOX DISABLED: generated code runs as a plain host process with this "
                     "user's file and network access (AETHER_SANDBOX=none). Development only.")
        return NoSandboxRunner(limits)
    backends = {"docker": DockerRunner, "macos": MacSandboxRunner}
    if choice not in backends:
        raise SandboxUnavailable(f"unknown AETHER_SANDBOX={choice!r}; use docker, macos or none")
    runner = DockerRunner(limits, img=browser_image()) if choice == "docker" and profile == "browser" \
        else backends[choice](limits)
    if not runner.available():
        raise SandboxUnavailable(f"sandbox backend {choice!r} is not available on this host; "
                                 "refusing to run generated code")
    return runner
