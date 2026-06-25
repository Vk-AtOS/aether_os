"""
Tests for DCSP CLI tool.
"""

import subprocess
import sys
from pathlib import Path

CLI_PATH = Path(__file__).parent.parent / "dcsp_cli.py"

def test_status_command_runs():
    """Verify that 'status' command runs without crashing."""
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), "status"],
        capture_output=True,
        text=True
    )
    # Even if API is down, it should print a message and exit with 0
    assert result.returncode == 0
    assert "DCSP" in result.stdout or "could not connect" in result.stdout

def test_health_command_runs():
    """Verify that 'health' command runs without crashing."""
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), "health"],
        capture_output=True,
        text=True
    )
    # If API is down, it should exit with 1
    # If API is up, it should exit with 0 or 1 depending on health
    # We just want to ensure it doesn't crash (stderr empty of tracebacks)
    assert "Traceback" not in result.stderr
