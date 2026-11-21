"""KAN-195: no shared default password / server address in shipped code, scripts or docs."""
import inspect
import pathlib
import re
import subprocess

import pytest

from aether_os.core.prompt_compiler import PromptCompiler
from aether_os.core.quality_monitor import QualityMonitor

ROOT = pathlib.Path(__file__).resolve().parents[1]
LITERALS = re.compile(r"Admin1234|User1234|demo1234|\b139\.59\.87\.218\b")
# core/guardian/password_shield.py lists demo1234 as a BLOCKED password.
SKIP = ("core/guardian/password_shield.py", "core/seed.py", "docs/AUDIT_2026_08_08.md",
        "docs/codebase_map/", "tests/", "snapshots/")


def test_quality_monitor_requires_password():
    p = inspect.signature(QualityMonitor.__init__).parameters
    assert p["admin_password"].default is inspect.Parameter.empty


def test_seed_few_shot_teaches_env_passwords():
    assert "Admin1234" not in PromptCompiler()._get_seed_few_shot()


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs a git checkout")
def test_no_credential_or_server_literals_in_tracked_files():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    bad = []
    for f in files:
        if not f or f.startswith(SKIP) or f in SKIP:
            continue
        try:
            text = (ROOT / f).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        bad += [f"{f}:{n}" for n, line in enumerate(text.splitlines(), 1) if LITERALS.search(line)]
    assert not bad, bad
