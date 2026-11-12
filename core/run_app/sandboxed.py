"""Python environment of a generated app, built inside the run's sandbox.

Generated requirements used to be pip-installed into the platform's own
interpreter. Now each run gets a virtualenv inside its run directory (the only
place a sandboxed process may write), layered on the base interpreter's
packages (--system-site-packages) so fastapi/uvicorn need no download. pip is
the base interpreter's, pointed at the venv with --python, which saves the
~10 s ensurepip costs per run.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from aether_os.core.sandbox.runner import SandboxRunner


def venv_python(runner: SandboxRunner, run_dir: Path, env: Mapping[str, str]) -> str:
    """Path of the run's venv interpreter, creating the venv on first use.

    One venv per backend: a venv made in the container links to the image's
    interpreter and would not run on the host, and the other way round.
    """
    venv = run_dir / f".venv-{runner.name}"
    python = venv / "bin" / "python"
    if not python.exists():
        made = runner.run([runner.base_python(), "-m", "venv", "--system-site-packages",
                           "--without-pip", str(venv)], run_dir=run_dir, env=env, timeout=120)
        if made.returncode != 0:
            raise RuntimeError(f"could not create the app's virtualenv: {made.stderr[-300:]!r}")
    return str(python)


def pip_install(runner: SandboxRunner, run_dir: Path, python: str, args: Sequence[str],
                env: Mapping[str, str], timeout: int) -> subprocess.CompletedProcess:
    """`pip install <args>` into the run's venv; the only Python step that gets network."""
    return runner.run([runner.base_python(), "-m", "pip", "--python", python, "install", *args,
                       "-q", "--no-warn-script-location"],
                      run_dir=run_dir, env=env, timeout=timeout, network=True)
