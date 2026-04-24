import subprocess
import sys
import os
from typing import Tuple


def check_syntax(file_path: str) -> Tuple[bool, str]:
    """
    Run a basic Python syntax check using `python -m py_compile`.

    Returns:
        (ok, message) where:
          ok = True if syntax is valid
          ok = False if syntax error found or command failed
    """
    abs_path = os.path.abspath(os.path.expanduser(file_path))

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
    abs_path = os.path.abspath(os.path.expanduser(file_path))

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
        return False, f"Failed to run: {e}"

    if result.returncode == 0:
        return True, result.stdout.strip() or "No output."
    else:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        msg = stderr if stderr else stdout if stdout else "Unknown runtime error"
        return False, msg

