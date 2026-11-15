import logging
import subprocess
import sys
import os
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

# Allowed root for sandboxed project files
_SANDBOX_ROOT = Path.home() / ".aether_os" / "projects"


def _validate_sandbox_path(file_path: str) -> str:
    """Resolve path and ensure it is within the sandbox root. Returns abs path or raises ValueError."""
    abs_path = Path(file_path).resolve()
    sandbox_root = _SANDBOX_ROOT.resolve()
    try:
        abs_path.relative_to(sandbox_root)
    except ValueError:
        raise ValueError(
            f"Path '{abs_path}' is outside the allowed sandbox directory '{sandbox_root}'"
        ) from None
    return str(abs_path)


def check_syntax(file_path: str) -> Tuple[bool, str]:
    """
    Run a basic Python syntax check using `python -m py_compile`.

    Returns:
        (ok, message) where:
          ok = True if syntax is valid
          ok = False if syntax error found or command failed
    """
    try:
        abs_path = _validate_sandbox_path(file_path)
    except ValueError as e:
        return False, str(e)

    if not os.path.isfile(abs_path):
        return False, f"File does not exist: {abs_path}"

    # Use the same Python interpreter running Aether-One
    python_exe = sys.executable

    try:
        result = subprocess.run(
            [python_exe, "-m", "py_compile", abs_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        logger.warning("check_python_syntax failed for %s: %s", file_path, e)
        return False, f"Failed to run syntax check: {e}"

    if result.returncode == 0:
        return True, "No syntax errors detected."
    else:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        msg = stderr if stderr else stdout if stdout else "Unknown error"
        return False, msg

def run_python_file(file_path: str) -> Tuple[bool, str]:
    """
    Run a Python file in isolation and capture runtime errors.

    Returns:
        (ok, message)
    """
    try:
        abs_path = _validate_sandbox_path(file_path)
    except ValueError as e:
        return False, str(e)

    if not os.path.isfile(abs_path):
        return False, f"File does not exist: {abs_path}"

    python_exe = sys.executable

    try:
        result = subprocess.run(
            [python_exe, abs_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        logger.warning("run_python_file failed for %s: %s", file_path, e)
        return False, f"Failed to run: {e}"

    if result.returncode == 0:
        return True, result.stdout.strip() or "No output."
    else:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        msg = stderr if stderr else stdout if stdout else "Unknown runtime error"
        return False, msg

