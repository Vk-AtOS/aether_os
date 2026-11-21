"""The one way pipeline phases run generated code: their tests, probes, builds and installs.

Phases used to call subprocess / asyncio.create_subprocess_exec directly, so generated
tests, import checks, `npm run build` and the app itself ran on the platform host with only
an environment allowlist. Everything now goes through SandboxRunner (core/sandbox/runner.py),
chosen by AETHER_SANDBOX exactly as for the run-app launcher:

  * the same limits (Limits) and environment allowlist (core/run_app/child_env.py), with HOME
    and TMPDIR inside the run directory (no cache shared across runs);
  * build, test and probe commands get NO network; installs (network=True) get the install
    egress profile of the Docker backend;
  * backend `none` (development flag) and `macos` behave as before for the command itself;
  * if no runner is available (production without Docker, unknown backend) SandboxUnavailable
    is raised and the generated code is NOT run: there is no host fallback.

The run directory is the project root (~/.aether_os/projects/<run_id>): the only place a
sandboxed command may write.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Mapping, Optional, Sequence

from aether_os.core.projects import get_project_manager
from aether_os.core.run_app.child_env import child_env
from aether_os.core.sandbox.endpoints import app_host, app_url  # noqa: F401  (the one way callers address a started app)
from aether_os.core.sandbox.runner import SandboxRunner, SandboxUnavailable, get_runner, sandbox_dirs

logger = logging.getLogger(__name__)

_TOOLS = ("npm", "npx", "node")


def project_root(path: Path) -> Path:
    """The run directory that contains `path` (its first folder under the projects root).

    Outside the projects root (a test, a one-off run) the path itself is the run directory.
    """
    real = Path(path).resolve()
    root = get_project_manager()._root.resolve()
    if real.is_relative_to(root) and real != root:
        return root / real.relative_to(root).parts[0]
    return real if real.is_dir() else real.parent


def _runner() -> SandboxRunner:
    try:
        return get_runner()
    except SandboxUnavailable as exc:
        logger.error("phase_exec: refusing to run generated code: %s", exc)
        raise SandboxUnavailable(f"generated code was not run: sandbox unavailable ({exc})") from exc


def _resolve(runner: SandboxRunner, argv: Sequence[str]) -> list:
    """`python3` -> the runner's interpreter; npm/npx/node -> the runner's toolchain path."""
    out = list(argv)
    if out[0] in ("python3", "python"):
        out[0] = runner.base_python()
    elif out[0] in _TOOLS:
        found = runner.tool(out[0])
        if not found:
            raise FileNotFoundError(f"{out[0]} is not available in the sandbox")
        out[0] = found
    return out


def run_sync(argv: Sequence[str], *, cwd: Path, project: Optional[Path] = None,
             env: Optional[Mapping[str, str]] = None, timeout: Optional[int] = None,
             network: bool = False, text: bool = False) -> subprocess.CompletedProcess:
    """Run one command in the sandbox. Raises subprocess.TimeoutExpired / SandboxUnavailable.

    `network=True` is for dependency installs only. `text=True` decodes stdout/stderr.
    """
    runner = _runner()
    root = project_root(project or cwd)
    full_env = child_env(PIP_DISABLE_PIP_VERSION_CHECK="1", **sandbox_dirs(root))
    full_env.update(env or {})
    done = runner.run(_resolve(runner, argv), run_dir=root, cwd=Path(cwd), env=full_env,
                      timeout=timeout, network=network)
    if text:
        return subprocess.CompletedProcess(done.args, done.returncode,
                                           (done.stdout or b"").decode(errors="replace"),
                                           (done.stderr or b"").decode(errors="replace"))
    return done


async def run(argv: Sequence[str], *, cwd: Path, project: Optional[Path] = None,
              env: Optional[Mapping[str, str]] = None, timeout: Optional[int] = None,
              network: bool = False, text: bool = False) -> subprocess.CompletedProcess:
    """Async run_sync. A timeout raises asyncio.TimeoutError (what the phases already handle)."""
    try:
        return await asyncio.to_thread(run_sync, argv, cwd=cwd, project=project, env=env,
                                       timeout=timeout, network=network, text=text)
    except subprocess.TimeoutExpired as exc:
        raise asyncio.TimeoutError(f"command timed out after {timeout}s") from exc


def start_app(argv: Sequence[str], *, cwd: Path, port: int, log_path: Path, project: Optional[Path] = None,
              env: Optional[Mapping[str, str]] = None):
    """Start a long-running generated app (a probe) in the sandbox; returns the runner's process handle
    (pid, poll(), terminate(), kill(), wait()). The caller reaches it on app_host():<port> (never a
    hard-coded 127.0.0.1: inside a gateway container that is the container itself). Write
    "{host}" in argv where the app's bind address goes (127.0.0.1, or 0.0.0.0 inside a container).
    Log output goes to `log_path` (opened O_NOFOLLOW)."""
    runner = _runner()
    argv = [a.replace("{host}", runner.bind_host) for a in argv]
    root = project_root(project or cwd)
    full_env = child_env(PIP_DISABLE_PIP_VERSION_CHECK="1", **sandbox_dirs(root))
    full_env.update(env or {})
    return runner.start(_resolve(runner, argv), run_dir=root, cwd=Path(cwd), env=full_env,
                        log_path=log_path, port=port, labels={"aether.probe": "1"})
