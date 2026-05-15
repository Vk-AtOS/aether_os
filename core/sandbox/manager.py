"""
Aether-One Sandbox Manager

Purpose
-------
Enterprise-grade execution layer that can safely run code:

- Locally (on the developer workstation / CI runner)
- On remote IoT / robotics / edge devices (via SSH)

This module does NOT call any LLMs. It is pure execution & isolation
logic designed to be used by:

- Fix engine (to validate patches)
- Test runner (to run tests in isolation)
- Robotics / IoT workflows (deploy & run small snippets remotely)
- CI/CD agent (pre-deploy checks)

Design
------
- Strongly-typed request/response objects
- Explicit limits (CPU time, wall-clock time, memory)
- Clean stdout/stderr capture
- Clear error reporting and timing info
- Optional device execution over SSH (paramiko)
"""

from __future__ import annotations

import dataclasses
import os
import shlex
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    import resource  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - Windows or restricted env
    resource = None  # type: ignore[assignment]

try:
    import paramiko  # type: ignore[import]
except ImportError:  # pragma: no cover - optional
    paramiko = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SandboxLimits:
    """
    Execution limits for sandboxed runs.

    cpu_time_sec:
        Approximate CPU time limit (Unix only; uses RLIMIT_CPU if available).

    wall_time_sec:
        Max wall-clock time before force-kill.

    memory_mb:
        Soft cap on address space (Unix only; RLIMIT_AS if available).
    """

    cpu_time_sec: int = 10
    wall_time_sec: int = 30
    memory_mb: int = 1024
    allow_network: bool = False  # reserved; local sandbox does not yet firewall


@dataclass
class DeviceConnectionConfig:
    """
    Connection details for a remote IoT/robotics device.

    Example:
        DeviceConnectionConfig(
            host="192.168.0.42",
            username="pi",
            port=22,
            auth_method="key",
            key_path="/home/user/.ssh/id_rsa",
        )
    """

    host: str
    username: str
    port: int = 22
    auth_method: str = "key"  # "key" or "password"
    key_path: Optional[str] = None
    password: Optional[str] = None
    # Optional: base remote working directory
    base_remote_dir: str = "/tmp/aetherone_sandbox"


@dataclass
class SandboxRequest:
    """
    Describe a single sandbox run.

    Attributes:
        language:
            "python", "shell", "bash", or other (treated as shell).

        code:
            For language-aware execution (e.g. python). If provided and
            command is None, code is written to a temp file and executed.

        command:
            Optional explicit command line to run. If provided, this
            takes precedence over `code`.

        work_dir:
            Working directory (local or remote). If None, a temporary
            directory may be created when appropriate.

        env:
            Environment variables to set.

        input_data:
            Optional stdin content as text.

        limits:
            SandboxLimits describing resource caps.

        target_type:
            "local" or "device".

        device_config:
            Required when target_type == "device".
    """

    language: str
    code: Optional[str] = None
    command: Optional[str] = None
    work_dir: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    input_data: Optional[str] = None
    limits: SandboxLimits = dataclasses.field(default_factory=SandboxLimits)
    target_type: str = "local"  # "local" | "device"
    device_config: Optional[DeviceConnectionConfig] = None


@dataclass
class SandboxResult:
    """
    Outcome of a sandbox run.
    """

    ok: bool
    exit_code: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool
    killed: bool
    started_at: str
    finished_at: str
    duration_sec: float
    target_type: str
    target_host: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Local sandbox backend
# ---------------------------------------------------------------------------


class LocalSandboxBackend:
    """
    Local sandbox implementation using subprocess and (if available) Unix
    resource limits (CPU, address space).

    This respects Python virtualenv and runs commands in the current process
    environment by default.
    """

    def __init__(self) -> None:
        pass

    def _build_command(self, req: SandboxRequest, temp_dir: str) -> str:
        # Explicit command wins
        if req.command:
            return req.command

        lang = (req.language or "").strip().lower()

        if lang == "python":
            if not req.code:
                raise ValueError("Python sandbox request requires `code` or `command`.")
            # Write code to temp file
            script_path = os.path.join(temp_dir, "sandbox_code.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(req.code)
            return f"{shlex.quote(self._python_executable())} {shlex.quote(script_path)}"

        # Default: treat as shell
        if not req.code:
            raise ValueError("Shell sandbox request requires `code` or `command`.")
        return req.code

    def _python_executable(self) -> str:
        # Use current Python interpreter
        return os.environ.get("PYTHON_EXECUTABLE", os.sys.executable)

    def _apply_resource_limits(self, limits: SandboxLimits) -> None:
        if resource is None:
            return  # not supported on this platform

        # CPU time limit
        if limits.cpu_time_sec > 0:
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_time_sec, limits.cpu_time_sec))
            except Exception:
                pass

        # Address space limit (rough bound)
        if limits.memory_mb > 0:
            limit_bytes = limits.memory_mb * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
            except Exception:
                pass

    def run(self, req: SandboxRequest) -> SandboxResult:
        if req.target_type != "local":
            raise ValueError("LocalSandboxBackend can only handle target_type='local'.")

        started = datetime.now(timezone.utc)
        stdout_text = ""
        stderr_text = ""
        exit_code: Optional[int] = None
        timed_out = False
        killed = False
        error_msg: Optional[str] = None

        work_dir = req.work_dir or tempfile.mkdtemp(prefix="aetherone_local_sandbox_")

        env = os.environ.copy()
        if req.env:
            env.update(req.env)

        try:
            with tempfile.TemporaryDirectory(prefix="aetherone_local_code_", dir=work_dir) as tmp:
                cmd = self._build_command(req, temp_dir=tmp)

                if req.language.strip().lower() in ("shell", "bash", "sh"):
                    shell = False
                    args = ["/bin/sh", "-c", cmd]
                else:
                    # Python command was built with shlex.quote, safe to split
                    import shlex as _shlex_split
                    shell = False
                    args = _shlex_split.split(cmd)

                def preexec() -> None:
                    # New process group for safe kill
                    os.setsid()
                    self._apply_resource_limits(req.limits)

                proc = subprocess.Popen(
                    args,
                    shell=shell,
                    cwd=work_dir,
                    env=env,
                    stdin=subprocess.PIPE if req.input_data is not None else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    preexec_fn=preexec if os.name != "nt" else None,
                )

                try:
                    stdout_text, stderr_text = proc.communicate(
                        input=req.input_data,
                        timeout=req.limits.wall_time_sec,
                    )
                    exit_code = proc.returncode
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        if os.name != "nt":
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        else:
                            proc.kill()
                        killed = True
                    except Exception:
                        pass
                    stdout_text, stderr_text = proc.communicate()
                    exit_code = proc.returncode

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"

        finished = datetime.now(timezone.utc)
        duration = (finished - started).total_seconds()

        ok = (error_msg is None) and (exit_code == 0) and not timed_out

        return SandboxResult(
            ok=ok,
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            timed_out=timed_out,
            killed=killed,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            duration_sec=duration,
            target_type="local",
            target_host=None,
            error=error_msg,
        )


# ---------------------------------------------------------------------------
# Device (SSH) sandbox backend
# ---------------------------------------------------------------------------


class DeviceSandboxBackend:
    """
    Remote sandbox using SSH for IoT / robotics / edge devices.

    This backend:
        - Connects to a remote host via SSH (using paramiko)
        - Creates a temp directory (under base_remote_dir)
        - Writes the code to a script file (for python or shell)
        - Executes the script and captures stdout/stderr/exit code

    It assumes a reasonably Unix-like target (POSIX shell, python available
    if language='python').
    """

    def __init__(self) -> None:
        if paramiko is None:
            raise RuntimeError(
                "DeviceSandboxBackend requires `paramiko`. "
                "Install with: pip install paramiko"
            )

    def run(self, req: SandboxRequest) -> SandboxResult:
        if req.target_type != "device":
            raise ValueError("DeviceSandboxBackend can only handle target_type='device'.")

        if req.device_config is None:
            raise ValueError("DeviceSandboxBackend requires device_config for device target.")

        cfg = req.device_config
        started = datetime.now(timezone.utc)
        stdout_text = ""
        stderr_text = ""
        exit_code: Optional[int] = None
        timed_out = False
        killed = False
        error_msg: Optional[str] = None

        client = paramiko.SSHClient()  # type: ignore[call-arg]
        # RejectPolicy refuses unknown host keys — prevents MITM on SSH sandbox connections.
        # Known hosts must be pre-populated via cfg.known_hosts_file or the system's known_hosts.
        known_hosts = getattr(cfg, "known_hosts_file", None)
        if known_hosts:
            client.load_host_keys(known_hosts)
        else:
            client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())  # type: ignore[attr-defined]

        try:
            connect_args: Dict[str, Any] = {
                "hostname": cfg.host,
                "port": cfg.port,
                "username": cfg.username,
                "timeout": 10,
            }
            if cfg.auth_method == "key":
                if not cfg.key_path:
                    raise ValueError("device_config.key_path is required for auth_method='key'.")
                connect_args["key_filename"] = cfg.key_path
            elif cfg.auth_method == "password":
                if not cfg.password:
                    raise ValueError("device_config.password is required for auth_method='password'.")
                connect_args["password"] = cfg.password
            else:
                raise ValueError(f"Unknown auth_method: {cfg.auth_method!r}")

            client.connect(**connect_args)  # type: ignore[arg-type]

            sftp = client.open_sftp()
            try:
                # Prepare remote directory
                base = cfg.base_remote_dir.rstrip("/") or "/tmp"
                remote_dir = f"{base}/run_{int(time.time())}"
                try:
                    sftp.mkdir(base)
                except IOError:
                    pass  # ignore if exists
                sftp.mkdir(remote_dir)

                # Decide commands & script path
                lang = (req.language or "").strip().lower()
                if req.command:
                    remote_cmd = req.command
                    remote_script_path = None
                else:
                    if not req.code:
                        raise ValueError("Device sandbox requires `code` or `command`.")
                    if lang == "python":
                        remote_script_path = f"{remote_dir}/sandbox_code.py"
                        with sftp.file(remote_script_path, "w") as f:
                            f.write(req.code)
                        remote_cmd = f"python {shlex.quote(remote_script_path)}"
                    else:
                        # Default to shell script
                        remote_script_path = f"{remote_dir}/sandbox_script.sh"
                        with sftp.file(remote_script_path, "w") as f:
                            f.write(req.code)
                        # Make executable
                        sftp.chmod(remote_script_path, 0o755)
                        remote_cmd = remote_script_path

                # Build environment prefix
                env_prefix = ""
                if req.env:
                    exports = []
                    for k, v in req.env.items():
                        exports.append(f'{shlex.quote(k)}={shlex.quote(v)}')
                    env_prefix = " ".join(exports) + " "

                # Full command
                work_dir = req.work_dir or remote_dir
                full_cmd = f"cd {shlex.quote(work_dir)} && {env_prefix}{remote_cmd}"

                # Execute with a timeout
                chan = client.get_transport().open_session()  # type: ignore[union-attr]
                chan.settimeout(req.limits.wall_time_sec)
                chan.exec_command(full_cmd)

                # Handle stdin if provided
                if req.input_data is not None:
                    chan.sendall(req.input_data)
                    chan.shutdown_write()

                stdout_chunks: List[str] = []
                stderr_chunks: List[str] = []

                start_wall = time.time()
                while True:
                    if chan.recv_ready():
                        stdout_chunks.append(chan.recv(4096).decode("utf-8", errors="replace"))
                    if chan.recv_stderr_ready():
                        stderr_chunks.append(chan.recv_stderr(4096).decode("utf-8", errors="replace"))

                    if chan.exit_status_ready():
                        break

                    if (time.time() - start_wall) > req.limits.wall_time_sec:
                        timed_out = True
                        try:
                            chan.close()
                            killed = True
                        except Exception:
                            pass
                        break

                    time.sleep(0.1)

                # Flush remaining
                try:
                    while chan.recv_ready():
                        stdout_chunks.append(chan.recv(4096).decode("utf-8", errors="replace"))
                    while chan.recv_stderr_ready():
                        stderr_chunks.append(chan.recv_stderr(4096).decode("utf-8", errors="replace"))
                except Exception:
                    pass

                stdout_text = "".join(stdout_chunks)
                stderr_text = "".join(stderr_chunks)

                if not timed_out:
                    try:
                        exit_code = chan.recv_exit_status()
                    except Exception:
                        exit_code = None

            finally:
                sftp.close()

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
        finally:
            try:
                client.close()
            except Exception:
                pass

        finished = datetime.now(timezone.utc)
        duration = (finished - started).total_seconds()

        ok = (error_msg is None) and (exit_code == 0) and not timed_out

        return SandboxResult(
            ok=ok,
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            timed_out=timed_out,
            killed=killed,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            duration_sec=duration,
            target_type="device",
            target_host=cfg.host,
            error=error_msg,
        )


# ---------------------------------------------------------------------------
# Sandbox Manager (router)
# ---------------------------------------------------------------------------


class SandboxManager:
    """
    High-level router that picks the correct backend (local vs device)
    based on SandboxRequest.target_type.

    This is what higher-level modules (fix engine, tests, CI, robotics)
    will use.
    """

    def __init__(
        self,
        local_backend: Optional[LocalSandboxBackend] = None,
        device_backend: Optional[DeviceSandboxBackend] = None,
    ) -> None:
        self._local = local_backend or LocalSandboxBackend()
        self._device = device_backend

    def _ensure_device_backend(self) -> DeviceSandboxBackend:
        if self._device is None:
            # Lazily create to avoid paramiko import cost when not needed
            self._device = DeviceSandboxBackend()
        return self._device

    def run(self, req: SandboxRequest) -> SandboxResult:
        target = (req.target_type or "local").strip().lower()
        if target == "local":
            return self._local.run(req)
        elif target == "device":
            backend = self._ensure_device_backend()
            return backend.run(req)
        else:
            raise ValueError(f"Unknown sandbox target_type: {req.target_type!r}")


# ---------------------------------------------------------------------------
# Convenience function & singleton
# ---------------------------------------------------------------------------

_default_manager: Optional[SandboxManager] = None


def get_default_manager() -> SandboxManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = SandboxManager()
    return _default_manager


def run_sandbox(request: SandboxRequest) -> SandboxResult:
    """
    Convenience function:

        result = run_sandbox(SandboxRequest(...))
    """
    mgr = get_default_manager()
    return mgr.run(request)

