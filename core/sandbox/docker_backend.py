"""Production sandbox: one Docker container per generated-code command.

Every container (docker_args is the single place the policy lives, unit-tested):
  * runs as a non-root uid, `--cap-drop ALL`, `no-new-privileges`, Docker's
    default seccomp profile (never `unconfined`), read-only root filesystem;
  * sees exactly one host path: the run directory, read-write, bind-mounted at
    the same absolute path (plus a small noexec /tmp tmpfs);
  * has memory (no extra swap), CPU, pids, open-file and file-size limits;
  * gets only the allowlisted environment (core/run_app/child_env.py);
  * network, decided per command:
      - "none"            build steps, tests, migrations: no network at all;
      - EGRESS_NETWORK    dependency installs only (pip/npm): internet egress;
                          host_firewall.sh drops private ranges, link-local
                          (cloud metadata) and the host itself on this bridge;
      - RUN_NETWORK       the running app: its port is published on
                          AETHER_SANDBOX_PUBLISH_IP only; the bridge has no
                          masquerade (no internet) and host_firewall.sh drops
                          every new connection from it to the host or anywhere.
    Both are separate bridge networks with inter-container traffic disabled,
    so the platform's own containers (Postgres, Redis, API) are unreachable.
  * one-shot commands are killed (`docker rm -f`) at their timeout and their
    output is capped.

Decision on install egress: package installs run with public internet egress
(install hooks of pip/npm packages are untrusted code too, but they run in this
container, with no route to private addresses, the host or the platform); the
app itself, its build, tests and probes run without egress. available() proves the
firewall is applied (isolation_probe.py) instead of trusting that host_firewall.sh ran. An allowlisted
package proxy would be stricter; add it if installs must be restricted further.

The run directory is mounted at the path the gateway sees. If the gateway itself
runs in a container, it must see the run directories at the same path as the
host (docker-compose.yml bind-mounts /home/aether/.aether_os at that path).
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from aether_os.core.errors import SandboxViolation
from aether_os.core.sandbox.isolation_probe import isolation_problem
from aether_os.core.sandbox.runner import Limits, SandboxRunner, cap_output

logger = logging.getLogger(__name__)

DOCKER = "docker"
RUN_NETWORK = "aether-sbx-run"
EGRESS_NETWORK = "aether-sbx-egress"
NETWORKS = {
    # name: (bridge interface, internet masquerade) — host_firewall.sh matches the interfaces.
    RUN_NETWORK: ("br-aether-run", False),
    EGRESS_NETWORK: ("br-aether-egr", True),
}
LABEL_RUN, LABEL_NONCE = "aether.run", "aether.nonce"
_CLI_TIMEOUT = 30


def image() -> str:
    return os.environ.get("AETHER_SANDBOX_IMAGE", "aether-sandbox:1")


def publish_ip() -> str:
    return os.environ.get("AETHER_SANDBOX_PUBLISH_IP", "127.0.0.1")


def sandbox_user() -> str:
    """uid:gid for containers: the gateway's own (so it can manage the run dir), never root."""
    configured = os.environ.get("AETHER_SANDBOX_UID")
    if configured:
        return configured
    uid, gid = os.getuid(), os.getgid()
    return f"{uid}:{gid}" if uid != 0 else "10001:10001"


def network_create_args(name: str) -> List[str]:
    bridge, masquerade = NETWORKS[name]
    return [DOCKER, "network", "create", "--driver", "bridge",
            "-o", f"com.docker.network.bridge.name={bridge}",
            "-o", "com.docker.network.bridge.enable_icc=false",
            "-o", f"com.docker.network.bridge.enable_ip_masquerade={str(masquerade).lower()}",
            name]


def docker_args(*, name: str, run_dir: Path, cwd: Path, argv: Sequence[str],
                env: Mapping[str, str], limits: Limits, network: str, user: str,
                img: str, host_run_dir: Optional[Path] = None,
                publish: Optional[Tuple[str, int]] = None,
                labels: Mapping[str, str] = (), detach: bool = False) -> List[str]:
    """`docker run` argv for one sandboxed command. Pure; raises SandboxViolation on a bad policy."""
    run_dir, cwd = Path(run_dir), Path(cwd)
    if not run_dir.is_absolute() or len(run_dir.parts) < 3:
        raise SandboxViolation(f"run dir must be a specific absolute directory, got {run_dir}")
    if not cwd.is_absolute() or not cwd.is_relative_to(run_dir):
        raise SandboxViolation(f"working directory {cwd} is outside the run dir {run_dir}")
    if user.split(":")[0] in ("0", "root", ""):
        raise SandboxViolation("sandbox containers never run as root")
    if network != "none" and network not in NETWORKS:
        raise SandboxViolation(f"network {network!r} is not a sandbox network")
    if publish and network != RUN_NETWORK:
        raise SandboxViolation("only the app network publishes a port")
    args = [
        DOCKER, "run", "--rm", "--name", name,
        "--user", user,
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", f"{limits.memory_mb}m", "--memory-swap", f"{limits.memory_mb}m",
        "--cpus", str(limits.cpus),
        "--pids-limit", str(limits.pids),
        "--ulimit", f"fsize={limits.file_bytes}:{limits.file_bytes}",
        "--ulimit", "nofile=1024:1024",
        "--init",
        "--network", network,
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--mount", f"type=bind,src={host_run_dir or run_dir},dst={run_dir}",
        "--workdir", str(cwd),
    ]
    if publish:
        args += ["--publish", f"{publish[0]}:{publish[1]}:{publish[1]}"]
    for key, value in sorted(dict(labels).items()):
        args += ["--label", f"{key}={value}"]
    for key, value in sorted(env.items()):
        if key != "PATH":  # the image's PATH, not the host's
            args += ["--env", f"{key}={value}"]
    if detach:
        args.append("--detach")
    return [*args, img, *argv]


def _docker(*args: str, timeout: int = _CLI_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run([DOCKER, *args], capture_output=True, text=True, timeout=timeout)


def _docker_cli(args: Sequence[str]) -> Tuple[int, str]:
    out = _docker(*args, timeout=60)
    return out.returncode, out.stdout


def remove_container(container: str) -> None:
    try:
        _docker("rm", "-f", container)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("sandbox: could not remove container %s: %s", container, exc)


def is_launched_container(container: object, nonce: object) -> bool:
    """True only if `container` is running and carries this launch's nonce label."""
    if not isinstance(container, str) or not container or not isinstance(nonce, str) or len(nonce) < 16:
        return False
    try:
        out = _docker("inspect", "-f", f'{{{{.State.Running}}}} {{{{index .Config.Labels "{LABEL_NONCE}"}}}}',
                      container)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("sandbox: docker inspect %s failed: %s", container, exc)
        return False
    return out.returncode == 0 and out.stdout.split() == ["true", nonce]


class ContainerProcess:
    """Popen-shaped handle on a detached container (what the run-app code expects)."""

    def __init__(self, container: str) -> None:
        self.container_id = container
        self.pid = None
        self.returncode: Optional[int] = None

    def poll(self) -> Optional[int]:
        """None while running; else the container's exit code (-1 when it no longer exists)."""
        if self.returncode is None:
            out = _docker("inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", self.container_id)
            parts = out.stdout.split()
            if out.returncode != 0 or len(parts) != 2:
                self.returncode = -1
            elif parts[0] != "true":
                self.returncode = int(parts[1]) if parts[1].lstrip("-").isdigit() else -1
        return self.returncode

    def terminate(self) -> None:
        _docker("stop", "-t", "5", self.container_id)

    def kill(self) -> None:
        remove_container(self.container_id)
        self.returncode = -9

    def wait(self, timeout: Optional[float] = None) -> int:
        try:
            out = _docker("wait", self.container_id, timeout=int(timeout or 3600))
        except subprocess.TimeoutExpired:
            raise subprocess.TimeoutExpired(["docker", "wait", self.container_id], timeout) from None
        if self.returncode is None:   # `docker wait` prints the exit code; unreadable output counts as a failure
            text = out.stdout.strip()
            self.returncode = int(text) if out.returncode == 0 and text.lstrip("-").isdigit() else -1
        return self.returncode


class DockerRunner(SandboxRunner):
    name = "docker"
    bind_host = "0.0.0.0"  # inside the container; reachable only through the published port

    def __init__(self, limits: Limits = Limits()) -> None:
        super().__init__(limits)
        self._img, self._user = image(), sandbox_user()

    def available(self) -> bool:
        try:
            if _docker("version", "--format", "{{.Server.Version}}").returncode != 0:
                return False
            if _docker("image", "inspect", self._img).returncode != 0:
                logger.error("sandbox: image %s not built (docker build -f core/sandbox/Dockerfile "
                             "-t %s core/sandbox)", self._img, self._img)
                return False
            for net in NETWORKS:
                if _docker("network", "inspect", net).returncode != 0:
                    created = subprocess.run(network_create_args(net), capture_output=True, text=True,
                                             timeout=_CLI_TIMEOUT)
                    if created.returncode != 0:
                        logger.error("sandbox: cannot create network %s: %s", net, created.stderr)
                        return False
            # The networks existing proves nothing: verify host_firewall.sh is really applied.
            problem = isolation_problem(_docker_cli, image=self._img, user=self._user,
                                        networks={RUN_NETWORK: False, EGRESS_NETWORK: True})
            if problem:
                logger.error("sandbox: refusing to run generated code: %s", problem)
                return False
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("sandbox: docker not available: %s", exc)
            return False

    def base_python(self) -> str:
        return "python3"

    def tool(self, name: str) -> Optional[str]:
        return name  # resolved on the image's PATH

    def _args(self, argv, run_dir: Path, cwd: Path, env, network: str, **kw) -> List[str]:
        name = f"aether-sbx-{os.urandom(6).hex()}"
        return docker_args(name=name, run_dir=run_dir.resolve(), cwd=cwd.resolve(), argv=argv, env=env,
                           limits=self.limits, network=network, user=self._user, img=self._img, **kw)

    def run(self, argv, *, run_dir, cwd=None, env, timeout=None, network=False):
        args = self._args(argv, run_dir, cwd or run_dir, env, EGRESS_NETWORK if network else "none")
        name = args[args.index("--name") + 1]
        try:
            done = subprocess.run(args, capture_output=True, timeout=timeout or self.limits.timeout_s)
        except subprocess.TimeoutExpired:
            remove_container(name)  # killing the CLI does not stop the container
            raise
        return subprocess.CompletedProcess(argv, done.returncode,
                                           cap_output(done.stdout, self.limits.output_bytes),
                                           cap_output(done.stderr, self.limits.output_bytes))

    def start(self, argv, *, run_dir, cwd, env, log_path, port, labels):
        # Output goes to the run's log file from inside the container (read-only root, no log driver).
        wrapped = ["/bin/sh", "-c", 'exec "$@" >>"$0" 2>&1', str(log_path), *argv]
        args = self._args(wrapped, run_dir, cwd, env, RUN_NETWORK, publish=(publish_ip(), port),
                          labels=labels, detach=True)
        out = subprocess.run(args, capture_output=True, text=True, timeout=_CLI_TIMEOUT)
        if out.returncode != 0:
            raise SandboxViolation(f"container did not start: {out.stderr.strip()[-400:]}")
        return ContainerProcess(out.stdout.strip())


def labels_for(run_id: str, nonce: str) -> Dict[str, str]:
    return {LABEL_RUN: run_id, LABEL_NONCE: nonce}
