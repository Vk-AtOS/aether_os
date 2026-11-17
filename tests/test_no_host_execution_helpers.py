"""KAN-69 SC-05: the three host-execution helpers (one copied the whole environment) had no caller and are gone;
generated code only runs through the sandbox runner."""
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[1] / "core" / "sandbox"


def test_unused_host_execution_helpers_stay_deleted():
    assert [n for n in ("guard.py", "manager.py", "python_tools.py") if (SANDBOX / n).exists()] == []
