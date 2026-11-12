"""macOS development sandbox: sandbox-exec (Seatbelt) around each generated-code process.

What it enforces (verified by tests/test_sandbox_macos.py on this machine):
  * no reading file contents under /Users, /Volumes, /private/tmp or
    /private/var/folders except the run directory and the toolchain
    (Python / Node install dirs) — so not the user's files, the platform code,
    its .env, ~/.ssh, other runs' directories or the platform's temp files;
  * no writing anywhere except the run directory (and /dev/null, ttys);
  * no outbound connection to this machine: every TCP/UDP port on localhost
    and on this host's own addresses (Postgres, Redis, the gateway, Ollama...)
    and every Unix socket except the DNS resolver's (so not Postgres' socket);
  * per-process limits: CPU seconds for one-shot commands, largest file size;
  * environment allowlist (core/run_app/child_env.py), HOME/TMPDIR in the run dir.

What it does NOT protect against — do not treat it as a security boundary:
  * other hosts on the LAN and the internet are reachable (Seatbelt cannot
    filter by address range); so is cloud metadata if the Mac has any;
  * file *metadata* is readable everywhere (names, sizes, mtimes of files in
    the user's home), as are system files outside the denied trees;
  * no memory, process-count or CPU-share limit (RLIMIT_AS is not enforced
    on macOS and RLIMIT_NPROC counts all of the user's processes);
  * other processes are visible (`ps`), including other runs' command lines;
    signals to the user's other processes are not blocked;
  * kernel / sandbox-exec escapes; sandbox-exec is deprecated by Apple;
  * a generated app can rewrite files in its own run directory, including the
    run's state file (the preview server re-verifies the app by its nonce).
Production uses the Docker backend.
"""
from __future__ import annotations

import logging
import os
import resource
import shutil
import site
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List

from aether_os.core.sandbox.runner import Limits, SandboxRunner

logger = logging.getLogger(__name__)

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_DENY_READ_TREES = ("/Users", "/Volumes", "/private/tmp", "/private/var/folders")
_DNS_SOCKET = "/private/var/run/mDNSResponder"


def _q(path: str) -> str:
    """SBPL string literal."""
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def macos_profile(run_dir: Path, readable: Iterable[Path] = ()) -> str:
    """Seatbelt profile for one run. Pure: paths in, profile text out.

    Later rules win in SBPL, so each deny is followed by its narrow allows.
    Paths are resolved because the kernel matches on real paths (/private/...).
    """
    run = str(Path(run_dir).resolve())
    lines = ["(version 1)", "(allow default)"]
    lines += [f"(deny file-read-data (subpath {_q(t)}))" for t in _DENY_READ_TREES]
    lines += [f"(allow file-read-data (subpath {_q(str(Path(p).resolve()))}))" for p in readable]
    lines.append(f"(allow file-read-data (subpath {_q(run)}))")
    lines += [
        '(deny file-write* (subpath "/"))',
        f"(allow file-write* (subpath {_q(run)}) (literal \"/dev/null\") (literal \"/dev/tty\")"
        ' (literal "/dev/dtracehelper") (regex #"^/dev/fd/") (regex #"^/dev/ttys"))',
        # "localhost" in Seatbelt covers loopback and this host's own addresses.
        '(deny network-outbound (remote ip "localhost:*"))',
        "(deny network-outbound (remote unix-socket))",
        f"(allow network-outbound (remote unix-socket (path-literal {_q(_DNS_SOCKET)})))",
    ]
    return "\n".join(lines) + "\n"


def _toolchain_dirs() -> List[Path]:
    """Install dirs of the interpreters generated code needs, when they live under a denied tree
    (e.g. Node from nvm in ~/.nvm). Everything else (Homebrew, /usr) is readable anyway."""
    candidates = [Path(sys.base_prefix), *map(Path, site.getsitepackages())]
    node = shutil.which("node")
    if node:
        candidates.append(Path(node).resolve().parent.parent)
    denied = tuple(Path(t) for t in _DENY_READ_TREES)
    out = []
    for c in candidates:
        real = c.resolve()
        if any(real.is_relative_to(d) for d in denied) and real != Path.home().resolve():
            out.append(real)
    return out


class MacSandboxRunner(SandboxRunner):
    name = "macos"

    def __init__(self, limits: Limits = Limits()) -> None:
        super().__init__(limits)

    def available(self) -> bool:
        if sys.platform != "darwin" or not os.path.exists(SANDBOX_EXEC):
            return False
        probe = subprocess.run([SANDBOX_EXEC, "-p", "(version 1)(allow default)", "/usr/bin/true"],
                               capture_output=True, timeout=10)
        return probe.returncode == 0

    def _argv(self, argv, run_dir: Path) -> List[str]:
        return [SANDBOX_EXEC, "-p", macos_profile(run_dir, _toolchain_dirs()), *argv]

    def _limits(self, cpu: bool):
        file_bytes, cpu_s = self.limits.file_bytes, self.limits.timeout_s

        def apply() -> None:  # runs in the child between fork and exec
            resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
            if cpu:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        return apply

    def run(self, argv, *, run_dir, cwd=None, env, timeout=None, network=False):
        # `network` only matters for Docker: here outbound internet is never blocked (see docstring).
        return self._host_run(self._argv(argv, run_dir), cwd or run_dir, env,
                              timeout or self.limits.timeout_s, preexec=self._limits(cpu=True))

    def start(self, argv, *, run_dir, cwd, env, log_path, port, labels):
        log = open(log_path, "a")
        return subprocess.Popen(self._argv(argv, run_dir), cwd=str(cwd), env=dict(env),
                                stdout=log, stderr=log, start_new_session=True,
                                preexec_fn=self._limits(cpu=False))
