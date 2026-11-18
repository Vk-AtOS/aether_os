"""KAN-69 SC-04: a `.bandit` file inside the generated tree cannot switch the scan off, and an empty report is an
error, not a clean result."""
import shutil
import subprocess
import sys

import pytest

from aether_os.core.security.bandit_run import BanditScanError, bandit_args, parse

pytestmark = pytest.mark.skipif(subprocess.run([sys.executable, "-m", "bandit", "--version"],
                                               capture_output=True).returncode != 0, reason="bandit not installed")


def test_parse_refuses_an_empty_or_broken_report():
    for bad in ("", "  \n", b"", None, "not json", "[]", "{}"):
        with pytest.raises(BanditScanError):
            parse(bad)
    assert parse('{"results": []}') == {"results": []}


def test_a_bandit_file_in_the_scanned_tree_does_not_skip_the_tests(tmp_path):
    (tmp_path / "a.py").write_text("import subprocess\nsubprocess.call('ls', shell=True)\n")
    (tmp_path / ".bandit").write_text("[bandit]\nskips = B602,B404,B603,B607,B605\n")
    plain = subprocess.run([sys.executable, "-m", "bandit", "-r", "-f", "json", "-q", str(tmp_path)],
                           capture_output=True, text=True)
    assert parse(plain.stdout)["results"] == []           # the attack works on the bare command
    ours = subprocess.run([sys.executable, "-m", "bandit", *bandit_args(tmp_path, "-q")], capture_output=True, text=True)
    assert {r["test_id"] for r in parse(ours.stdout)["results"]} >= {"B602"}
    shutil.rmtree(tmp_path / ".bandit", ignore_errors=True)


@pytest.mark.asyncio
async def test_scanner_and_quality_score_do_not_read_no_report_as_clean(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from aether_os.core.quality import metrics
    from aether_os.core.security import code_scanner
    empty = lambda *a, **k: SimpleNamespace(stdout="", stderr="boom", returncode=2)   # noqa: E731
    monkeypatch.setattr(code_scanner.subprocess, "run", empty)
    monkeypatch.setattr(code_scanner, "_run_pip_audit", lambda d: [])
    result = await code_scanner.CodeScanner().scan_project(str(tmp_path), "saas")
    assert not result.passed and any(f.rule_id == "SCAN_INCOMPLETE" for f in result.findings)
    monkeypatch.setattr(metrics.subprocess, "run", empty)
    assert metrics._check_security_bandit(tmp_path) == 0.0
