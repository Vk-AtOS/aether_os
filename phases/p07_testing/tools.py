"""
Aether-One Test Runner & Coverage Assistant (Core)

Goal:
    Provide a simple offline test runner utility that can be called from the
    orchestrator or agents to:

      - Run the project's test suite (e.g. pytest)
      - Capture stdout/stderr and exit code
      - Provide a basic summary of pass/fail status

This is the low-level core. Future upgrades can:
      - Integrate coverage.py data
      - Propose missing tests
      - Attach results into FixLogDB or knowledge base

Public API:

    run_tests(project_path: str, command: str = "pytest") -> dict
"""

from __future__ import annotations

import logging
import os
import shlex
from pathlib import Path
from typing import Dict, Any

from aether_os.core.sandbox import phase_exec

logger = logging.getLogger(__name__)


def run_tests(project_path: str, command: str = "pytest") -> Dict[str, Any]:
    """
    Run tests in the given project_path using the provided shell command.

    This function:
      - Changes working directory to project_path
      - Executes the command
      - Captures stdout, stderr, and exit code

    Returns:
      {
        "ok": bool,
        "exit_code": int,
        "command": str,
        "cwd": str,
        "stdout": str,
        "stderr": str,
      }
    """
    project_abs = os.path.abspath(os.path.expanduser(project_path))

    if not os.path.isdir(project_abs):
        return {
            "ok": False,
            "exit_code": -1,
            "command": command,
            "cwd": project_abs,
            "stdout": "",
            "stderr": f"project_path is not a directory: {project_abs}",
        }

    # Split command into args safely
    args = shlex.split(command)
    if args and args[0] in ("pytest", "py.test"):
        args = ["python3", "-m", "pytest", *args[1:]]  # the sandbox's interpreter, not a PATH lookup

    try:
        # Generated tests run in the sandbox only; SandboxUnavailable is reported, never bypassed.
        proc = phase_exec.run_sync(args, cwd=Path(project_abs), env={"PYTHONPATH": project_abs}, text=True)
    except FileNotFoundError as e:
        # E.g. pytest not installed
        return {
            "ok": False,
            "exit_code": -1,
            "command": command,
            "cwd": project_abs,
            "stdout": "",
            "stderr": f"Failed to run tests: {e}",
        }
    except Exception as e:
        logger.warning("p07_testing tools: unexpected error while running tests: %s", e)
        return {
            "ok": False,
            "exit_code": -1,
            "command": command,
            "cwd": project_abs,
            "stdout": "",
            "stderr": f"Unexpected error while running tests: {e}",
        }

    ok = (proc.returncode == 0)

    return {
        "ok": ok,
        "exit_code": proc.returncode,
        "command": command,
        "cwd": project_abs,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }

