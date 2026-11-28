"""The generated app's third-party packages for its tests (KAN-256).

Generated pytest runs used the sandbox image's base interpreter, which has only the common FastAPI stack: a generated
`import stripe` / `import boto3` crashed collection although requirements.txt lists it. The requirements are now
installed into a per-run directory that is put on PYTHONPATH for the test run.

The install is the one networked step that touches model-written input, so it is built to trust nothing in the run dir:
  * requirements.txt is read ONCE, every line is parsed with packaging (name, specifiers, extras, marker; no URL, no
    wheel/sdist file name) and the validated strings are passed to pip as argv. pip never opens a sandbox file (no
    `-r`, so nothing can change between check and use);
  * pip is the base interpreter's (`-I`), not the run venv's (an interpreter the sandbox could have replaced), with
    `--target` into a directory this process creates, a cwd/HOME/XDG_CONFIG_HOME that are fresh and empty, no pip
    config file, an explicit index, wheels only (no build script runs) and no cache;
  * the environment is a minimal allowlist: the caller's PYTHONPATH (the generated project) is never seen by pip.
A package with no wheel fails the step naming it. The packages dir sits in the run dir because that is the only
directory the container mounts; the runner interface has no read-only mount, so the pytest run can write it (the same
power it already has over the project's own files). Install success is recorded in the host-only state dir.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import List, Mapping, Optional

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from aether_os.core.run_app.preview_state import state_dir
from aether_os.core.sandbox.runner import SandboxRunner, SandboxUnavailable

logger = logging.getLogger(__name__)

INSTALL_TIMEOUT_S = 240
INDEX_URL = "https://pypi.org/simple"
_CANONICAL = re.compile(r"^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$", re.IGNORECASE)   # PEP 508 name
_ARCHIVE_SUFFIXES = (".whl", ".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")


class RequirementsRejected(RuntimeError):
    """The generated requirements.txt is not a plain list of packages (or one has no wheel): the step fails."""


_EXTRA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_OPS = ("==", "!=", "<=", ">=", "<", ">", "~=")
MAX_REQ_BYTES = 64 * 1024


def _rebuild(req: Requirement) -> str:
    """argv item from parsed parts only (never str(req)): PEP 503 name, checked extras, operators and versions."""
    spec = []
    for sp in sorted(req.specifier, key=str):
        v = sp.version
        if sp.operator not in _OPS:
            raise ValueError(f"operator {sp.operator!r} is not allowed")
        if v.endswith(".*"):
            if sp.operator not in ("==", "!="):
                raise ValueError("a wildcard version is only allowed with == and !=")
            v = v[:-2]
        Version(v)    # raises InvalidVersion: path-like or otherwise odd versions
        spec.append(f"{sp.operator}{sp.version}")
    extras = sorted(req.extras)
    if not all(_EXTRA.match(e) for e in extras):
        raise ValueError("bad extra name")
    out = canonicalize_name(req.name) + (f"[{','.join(extras)}]" if extras else "") + ",".join(spec)
    if req.marker is not None:
        out += f"; {req.marker}"
    return out


def read_requirements_file(path: Path, root: Path) -> str:
    """Contents of a regular file inside the run dir `root`, never through a symlink; capped. One read, no second open."""
    root_real = Path(os.path.realpath(root))
    if os.path.islink(path) or not stat.S_ISREG(os.lstat(path).st_mode):
        raise RequirementsRejected("requirements.txt is a symlink or not a regular file")
    if root_real not in Path(os.path.realpath(path)).parents:
        raise RequirementsRejected("requirements.txt resolves outside the run directory")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RequirementsRejected("requirements.txt is not a regular file")
        data = os.read(fd, MAX_REQ_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > MAX_REQ_BYTES:
        raise RequirementsRejected(f"requirements.txt is larger than {MAX_REQ_BYTES} bytes")
    return data.decode(errors="replace")


def parse_requirements(text: str) -> List[str]:
    """The rebuilt requirement strings. Raises RequirementsRejected naming the first offending line (truncated).

    Rejected: options (-e -r -c --index-url ...), URLs and `name @ url`, any '/' or '\\', wheel/sdist file names,
    ===, versions that are not PEP 440."""
    out: List[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if not line:
            continue
        why = None
        if line.startswith("-") or "://" in line or "/" in line or "\\" in line:
            why = "options, URLs and paths are not allowed"
        elif line.lower().endswith(_ARCHIVE_SUFFIXES):
            why = "archive file names are not allowed"
        else:
            try:
                req = Requirement(line)
                if req.url is not None:
                    why = "direct URL references are not allowed"
                elif not _CANONICAL.match(req.name):
                    why = "not a package name"
                else:
                    out.append(_rebuild(req))
            except (InvalidRequirement, InvalidVersion, ValueError) as exc:
                why = f"not an allowed requirement ({str(exc)[:60]})"
        if why:
            raise RequirementsRejected(f"requirements.txt line {n} rejected ({why}): {raw.strip()[:80]!r}")
    return out


def validate_requirements(text: str) -> None:
    parse_requirements(text)


def _pip_env(env: Mapping[str, str], home: Path, tmp: Path) -> dict:
    """Allowlist only. HOME / XDG_CONFIG_HOME are fresh empty dirs so no user pip config is read."""
    keep = {k: env[k] for k in ("PATH", "LANG", "LC_ALL") if k in env}
    keep.update(HOME=str(home), XDG_CONFIG_HOME=str(home), TMPDIR=str(tmp), PIP_CONFIG_FILE=os.devnull,
                PIP_NO_INPUT="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    return keep


def _marker(root: Path, key: str) -> Path:
    """Host-only marker (the gateway's state dir beside the run dirs): the sandbox cannot write it."""
    return state_dir(Path(root).name) / f"reqs-{key}"


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


def _real_dir(p: Path) -> bool:
    return p.is_dir() and not p.is_symlink()


def app_packages(runner: SandboxRunner, root: Path, cwd: Path, env: Mapping[str, str]) -> Optional[str]:
    """Directory with the app's requirements installed (for PYTHONPATH), or None to use the base packages only."""
    req = find_requirements(cwd, root)
    if req is None:
        return None
    try:
        reqs = parse_requirements(read_requirements_file(req, root))   # the one and only read
        if not reqs:
            return None
        key = hashlib.sha256("\n".join(sorted(reqs)).encode()).hexdigest()[:16]
        target, marker = Path(root) / f".deps-{key}", _marker(root, key)
        if marker.exists() and _real_dir(target):
            return str(target)
        work = Path(tempfile.mkdtemp(prefix=".pipwork-", dir=root))      # fresh, empty, created here
        try:
            cwd_dir, home = work / "cwd", work / "home"
            for d in (cwd_dir, home, work / "tmp", work / "target"):
                d.mkdir()
            done = runner.run(
                [runner.base_python(), "-I", "-m", "pip", "install", "--target", str(work / "target"),
                 "--index-url", INDEX_URL, "--only-binary=:all:", "--no-cache-dir", "-q",
                 "--no-warn-script-location", *reqs],
                run_dir=root, cwd=cwd_dir, env=_pip_env(env, home, work / "tmp"),
                timeout=INSTALL_TIMEOUT_S, network=True)
            if done.returncode != 0:
                err = (done.stderr or b"").decode(errors="replace")[-400:]
                missing = re.findall(r"No matching distribution found for ([\w.\-\[\]]+)", err)
                if missing:
                    raise RequirementsRejected(
                        f"{missing[0]} has no wheel for this platform (sdist builds are not run): {err}")
                logger.warning("sandbox: installing %s failed: %s", req.name, err)
                return None
            if target.is_symlink() or target.is_file():
                target.unlink()
            else:
                shutil.rmtree(target, ignore_errors=True)
            (work / "target").rename(target)
            marker.touch()
            return str(target)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    except (SandboxUnavailable, RequirementsRejected):
        raise   # no sandbox / refused input: nothing may run, least of all silently on other packages
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.warning("sandbox: no app packages for tests (%s): %s", req, exc)
        return None
