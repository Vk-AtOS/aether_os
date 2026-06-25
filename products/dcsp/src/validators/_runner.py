"""Shared subprocess helpers for DCSP language validators."""
from __future__ import annotations

import shutil
import subprocess


def run_cmd(
    cmd: list[str],
    cwd: str | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a command; returns CompletedProcess, never raises."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        input=input_text,
        timeout=30,
    )


def tool_on_path(name: str) -> bool:
    return shutil.which(name) is not None


def fmt_error(file_path: str, lineno: int | str, error_type: str, message: str) -> str:
    return f'File "{file_path}", line {lineno}: {error_type}: {message}'
