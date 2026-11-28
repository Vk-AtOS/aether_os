"""The generated app's own Python environment for its tests (KAN-256).

Generated pytest runs used the sandbox image's base interpreter, which has only the common FastAPI stack: a generated
`import stripe` / `import boto3` crashed collection with ModuleNotFoundError although the app's requirements.txt lists
it. The tests now run in the run's venv (core/run_app/sandboxed.py, the same one the Live App uses) with the app's
requirements installed over the install egress profile (public internet only, see host_firewall.sh). If the install
fails the tests still run on the base interpreter and pytest's own ModuleNotFoundError names the missing module; the
pip failure is logged with the same name.
"""
from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from pathlib import Path
from typing import Mapping, Optional

from aether_os.core.run_app.sandboxed import pip_install, venv_python
from aether_os.core.sandbox.runner import SandboxRunner, SandboxUnavailable

logger = logging.getLogger(__name__)

INSTALL_TIMEOUT_S = 240


def find_requirements(cwd: Path, root: Path) -> Optional[Path]:
    """requirements.txt in `cwd` or the nearest parent inside the run dir `root`."""
    cwd, root = Path(cwd).resolve(), Path(root).resolve()
    for d in (cwd, *cwd.parents):
        if d != root and root not in d.parents:
            break
        if (d / "requirements.txt").is_file():
            return d / "requirements.txt"
    return None


def is_pytest(argv) -> bool:
    return len(argv) >= 3 and argv[0] in ("python3", "python") and argv[1] == "-m" and argv[2] == "pytest"


def app_python(runner: SandboxRunner, root: Path, cwd: Path, env: Mapping[str, str]) -> Optional[str]:
    """Interpreter with the app's requirements installed (once per requirements content), or None to use the base one."""
    req = find_requirements(cwd, root)
    if req is None:
        return None
    try:
        python = venv_python(runner, root, env)
        marker = Path(python).parent.parent / f".reqs-{hashlib.sha256(req.read_bytes()).hexdigest()[:16]}"
        if marker.exists():
            return python
        done = pip_install(runner, root, python, ["-r", str(req)], env, INSTALL_TIMEOUT_S)
        if done.returncode != 0:
            err = (done.stderr or b"").decode(errors="replace")[-400:]
            missing = re.findall(r"No matching distribution found for ([\w.\-\[\]]+)", err)
            logger.warning("sandbox: installing %s failed%s: %s", req.name,
                           f" (package {missing[0]})" if missing else "", err)
            return None
        marker.touch()
        return python
    except SandboxUnavailable:
        raise   # no sandbox: nothing may run, least of all silently on a different interpreter
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.warning("sandbox: no app environment for tests (%s): %s", req, exc)
        return None
