"""Phases run pytest in the sandbox with --timeout=30; without pytest-timeout in the image pytest exits with
"unrecognized arguments" and collects nothing (production acceptance run 10, 22 Nov 2026: Stage 6 'no unit test ran')."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sandbox_image_has_pytest_timeout_when_phases_use_it():
    uses = [p for p in (ROOT / "phases").rglob("*.py") if re.search(r'["\']--timeout=\d+["\']', p.read_text())]
    assert uses, "no phase passes pytest --timeout; drop this test and the plugin together"
    assert re.search(r"\bpytest-timeout\b", (ROOT / "core" / "sandbox" / "Dockerfile").read_text())
