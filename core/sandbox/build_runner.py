"""Build a generated Dockerfile in a builder sandbox, not on the host daemon (KAN-99 / KAN-65).

`docker build` of a generated Dockerfile executes its RUN steps with the daemon's privileges, so it is
generated code running on the host. build_image runs kaniko (core/sandbox/Dockerfile.builder) in a
container instead:

  * no docker socket, not privileged, `--cap-drop ALL` with only the capabilities kaniko needs to unpack
    layers, `no-new-privileges`, memory / CPU / pids limits;
  * the run directory is the only host path, mounted at the same absolute path; the build context and the
    output tarball must both be inside it;
  * network: the install-egress bridge of the sandbox (public internet for base images and package installs,
    private ranges, link-local metadata and the host dropped by host_firewall.sh, verified by available());
  * no push: the result is a tarball in the run dir, which the platform `docker load`s (loading an image
    executes nothing).

Fail closed: no Docker daemon, sandbox networks without the verified firewall, or the builder image not
built raises SandboxUnavailable, and the Dockerfile is NOT built. There is no host `docker build` fallback.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import List

from aether_os.core.errors import SandboxViolation
from aether_os.core.sandbox.docker_backend import DOCKER, EGRESS_NETWORK, DockerRunner, _docker, remove_container
from aether_os.core.sandbox.runner import Limits, SandboxUnavailable, cap_output

logger = logging.getLogger(__name__)

# What kaniko needs to unpack and snapshot layers as root inside the container, and nothing else.
KANIKO_CAPS = ("CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID", "SETFCAP", "KILL")


def builder_image() -> str:
    return os.environ.get("AETHER_BUILDER_IMAGE", "aether-builder:1")


def builder_args(*, name: str, run_dir: Path, context: Path, tar_path: Path, tag: str,
                 limits: Limits, img: str) -> List[str]:
    """`docker run` argv for one build. Pure; raises SandboxViolation on a bad policy."""
    run_dir, context, tar_path = Path(run_dir), Path(context), Path(tar_path)
    if not run_dir.is_absolute() or len(run_dir.parts) < 3:
        raise SandboxViolation(f"run dir must be a specific absolute directory, got {run_dir}")
    for label, p in (("build context", context), ("output tarball", tar_path)):
        if not p.is_absolute() or not p.is_relative_to(run_dir):
            raise SandboxViolation(f"{label} {p} is outside the run dir {run_dir}")
    if not tag or any(c in tag for c in " \t\n;|&$`\"'"):
        raise SandboxViolation(f"image tag {tag!r} is not a plain name")
    caps = [a for c in KANIKO_CAPS for a in ("--cap-add", c)]
    return [
        DOCKER, "run", "--rm", "--name", name,
        "--cap-drop", "ALL", *caps,
        "--security-opt", "no-new-privileges",
        "--memory", f"{limits.memory_mb * 2}m", "--memory-swap", f"{limits.memory_mb * 2}m",
        "--cpus", str(limits.cpus * 2), "--pids-limit", str(limits.pids),
        "--init",
        "--network", EGRESS_NETWORK,
        "--mount", f"type=bind,src={run_dir},dst={run_dir}",
        img,
        "--context", f"dir://{context}",
        "--dockerfile", f"{context}/Dockerfile",
        "--no-push", "--tar-path", str(tar_path), "--destination", tag,
        "--verbosity", "warn",
    ]


def _require_builder(img: str) -> None:
    if not DockerRunner().available():     # daemon, sandbox networks, firewall proof (isolation_probe)
        raise SandboxUnavailable("docker sandbox is not available: the generated Dockerfile was not built")
    try:
        found = _docker("image", "inspect", img).returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxUnavailable(f"docker is not reachable: {exc}") from exc
    if not found:
        raise SandboxUnavailable(f"builder image {img} is not built "
                                 f"(docker build -f core/sandbox/Dockerfile.builder -t {img} core/sandbox)")


def build_image(app_dir: Path, image_name: str, *, run_dir: Path, timeout: int = 600,
                limits: Limits = Limits()) -> subprocess.CompletedProcess:
    """Build app_dir/Dockerfile in the builder sandbox and `docker load` the result as image_name.

    Raises SandboxUnavailable (no sandbox, nothing was built) and subprocess.TimeoutExpired. Returns the
    build's CompletedProcess (output capped); a failed build has returncode != 0 and nothing is loaded.
    """
    img = builder_image()
    _require_builder(img)
    run_dir, app_dir = Path(run_dir).resolve(), Path(app_dir).resolve()
    tar = run_dir / f".sandbox_tmp/{image_name}.tar"
    tar.parent.mkdir(parents=True, exist_ok=True)
    name = f"aether-build-{os.urandom(6).hex()}"
    args = builder_args(name=name, run_dir=run_dir, context=app_dir, tar_path=tar, tag=image_name,
                        limits=limits, img=img)
    try:
        done = subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        remove_container(name)      # killing the CLI does not stop the container
        raise
    result = subprocess.CompletedProcess(args, done.returncode, cap_output(done.stdout, limits.output_bytes),
                                         cap_output(done.stderr, limits.output_bytes))
    try:
        if done.returncode == 0:
            loaded = _docker("load", "-i", str(tar), timeout=300)
            if loaded.returncode != 0:
                return subprocess.CompletedProcess(args, loaded.returncode, b"", loaded.stderr.encode()[-2000:])
    finally:
        tar.unlink(missing_ok=True)
    return result
