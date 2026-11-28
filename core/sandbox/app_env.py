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

from aether_os.core.run_app.preview_state import state_dir
from aether_os.core.run_app.sandboxed import venv_python
from aether_os.core.sandbox.runner import SandboxRunner, SandboxUnavailable

logger = logging.getLogger(__name__)

INSTALL_TIMEOUT_S = 240

# `name[extras]<specifiers>` with an optional `; marker`. No options (-e -r -c --index-url ...), no URLs, no `name @ url`
# direct references, no VCS or local paths: those make pip fetch or run what the model chose.
_REQ_LINE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9._, -]+\])?"
    r"\s*((===|==|>=|<=|~=|!=|<|>)\s*[A-Za-z0-9.*+!_-]+\s*,?\s*)*"
    r"(;[^@#]*)?$")


class RequirementsRejected(RuntimeError):
    """The generated requirements.txt is not a plain list of packages (or one has no wheel): the step fails."""


def validate_requirements(text: str) -> None:
    """Raises RequirementsRejected naming the first offending line."""
    for n, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if line and (line.startswith("-") or "://" in line or not _REQ_LINE.match(line)):
            raise RequirementsRejected(
                f"requirements.txt line {n} is not a plain 'name[extras]<specifiers>' requirement: {raw.strip()!r}")


def _pip_env(env: Mapping[str, str], root: Path) -> dict:
    """Only what pip needs: the caller's env carries PYTHONPATH=<generated project> and other PYTHON* variables, which
    would load the generated code's sitecustomize/modules inside the networked install."""
    keep = {k: env[k] for k in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL") if k in env}
    keep["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return keep


def _marker(root: Path, req_bytes: bytes) -> Path:
    """Host-only marker (the gateway's state dir beside the run dirs): the sandbox can write the venv, not this."""
    return state_dir(Path(root).name) / f"reqs-{hashlib.sha256(req_bytes).hexdigest()[:16]}"


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
        data = req.read_bytes()
        validate_requirements(data.decode(errors="replace"))
        python = venv_python(runner, root, env)
        marker = _marker(root, data)
        if marker.exists():
            return python
        done = runner.run(
            [runner.base_python(), "-I", "-m", "pip", "--python", python, "install", "--only-binary=:all:",
             "-r", str(req), "-q", "--no-warn-script-location"],
            run_dir=root, cwd=Path(root) / ".sandbox_home", env=_pip_env(env, root),
            timeout=INSTALL_TIMEOUT_S, network=True)
        if done.returncode != 0:
            err = (done.stderr or b"").decode(errors="replace")[-400:]
            missing = re.findall(r"No matching distribution found for ([\w.\-\[\]]+)", err)
            if missing:
                raise RequirementsRejected(f"{missing[0]} has no wheel for this platform (sdist builds are not run): {err}")
            logger.warning("sandbox: installing %s failed: %s", req.name, err)
            return None
        marker.touch()
        return python
    except (SandboxUnavailable, RequirementsRejected):
        raise   # no sandbox: nothing may run, least of all silently on a different interpreter
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.warning("sandbox: no app environment for tests (%s): %s", req, exc)
        return None
