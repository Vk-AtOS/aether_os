"""Run browser work on a generated app inside the sandbox (KAN-99 / KAN-65).

The p05 preview screenshot, the p07c axe scan, the p07d Playwright specs and the s05 live axe result all
open a generated frontend in Chromium, which runs the generated JavaScript. None of them may do that on
the platform host: they describe the job as a dict and this module runs core/sandbox/browser/entry.py
through the sandbox runner with the "browser" profile (no network, run dir only). The static server for
the build and, when the job names one, the generated backend run on the container's own loopback, so
"localhost" inside the sandbox means the app under test and nothing else.

Fail closed like every other sandbox user: no runner (production without Docker, the browser image not
built) raises SandboxUnavailable and the generated frontend is not opened at all.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

from aether_os.core.run_app import safe_fs
from aether_os.core.run_app.child_env import child_env
from aether_os.core.sandbox.phase_exec import project_root
from aether_os.core.sandbox.runner import SandboxRunner, SandboxUnavailable, get_runner, sandbox_dirs

logger = logging.getLogger(__name__)


def _browser_runner() -> SandboxRunner:
    try:
        return get_runner(profile="browser")
    except SandboxUnavailable as exc:
        logger.error("browser_job: refusing to open generated code in a browser: %s", exc)
        raise SandboxUnavailable(f"generated frontend was not opened: browser sandbox unavailable ({exc})") from exc


def run_browser_job_sync(job: Dict[str, Any], *, project: Path, timeout: int = 120) -> Dict[str, Any]:
    """Run one job; returns the driver's JSON result ({"ok": bool, ...}).

    Every path in the job (dist dir, output file, spec, backend cwd) must be inside the run directory.
    Raises SandboxUnavailable (no sandbox) and subprocess.TimeoutExpired (job too slow).
    """
    runner = _browser_runner()
    root = project_root(project).resolve()
    for key in ("out", "spec", "cwd"):
        if job.get(key) and not Path(job[key]).resolve().is_relative_to(root):
            raise SandboxUnavailable(f"browser job {key} {job[key]} is outside the run dir {root}")
    for key in ("serve", "backend"):
        d = (job.get(key) or {}).get("dir") or (job.get(key) or {}).get("cwd")
        if d and not Path(d).resolve().is_relative_to(root):
            raise SandboxUnavailable(f"browser job {key} directory {d} is outside the run dir {root}")
    dirs = sandbox_dirs(root)
    tmp = Path(dirs["TMPDIR"])
    job_file = tmp / f"browser_job_{os.urandom(6).hex()}.json"
    safe_fs.safe_write_text(root, job_file, json.dumps(job))
    entry = runner.browser_entry()
    if runner.name != "docker":
        # host backends cannot read the platform tree: the driver is copied into the run dir
        copied = tmp / "browser_entry.py"
        shutil.copyfile(runner.browser_entry(), copied)
        entry = str(copied)
    env = child_env(PIP_DISABLE_PIP_VERSION_CHECK="1", **dirs)
    try:
        done = runner.run([runner.base_python(), entry, str(job_file)], run_dir=root, cwd=root, env=env,
                          timeout=timeout, network=False)
    finally:
        job_file.unlink(missing_ok=True)
    return parse_result(done)


def parse_result(done: subprocess.CompletedProcess) -> Dict[str, Any]:
    """The driver prints one JSON line last; anything else is a failed job with the tail of the output."""
    text = (done.stdout or b"").decode(errors="replace") if isinstance(done.stdout, bytes) else (done.stdout or "")
    for line in reversed(text.strip().splitlines()):
        try:
            result = json.loads(line)
        except ValueError:
            continue
        if isinstance(result, dict):
            return result
    err = (done.stderr or b"")
    err = err.decode(errors="replace") if isinstance(err, bytes) else err
    return {"ok": False, "error": f"browser job exited {done.returncode} without a result: {(text + err)[-400:]}"}


async def run_browser_job(job: Dict[str, Any], *, project: Path, timeout: int = 120) -> Dict[str, Any]:
    """Async wrapper (the job blocks for up to `timeout` s). A timeout raises asyncio.TimeoutError."""
    try:
        return await asyncio.to_thread(run_browser_job_sync, job, project=project, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise asyncio.TimeoutError(f"browser job timed out after {timeout}s") from exc
