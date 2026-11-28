"""KAN-250: p07a checks the app imports BEFORE pytest, and reads pytest from its JUnit report.

Runs 187dcfc3 + d7395a95: routers/crud.py raised NameError 'schemas' at import, pytest stopped at collection, the
"passed"/"failed" word count read that as 0 tests with no reason, and the import repair patched crud.py AFTER pytest,
so no test ever ran against the shipped file. The sandbox is faked here (phase_exec.run).
"""
import asyncio
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

from aether_os.phases.p07a_unit_testing import pytest_report
from aether_os.phases.p07a_unit_testing import task_agent as p07a
from aether_os.stages.s06_testing import supervisor as s06

_COLLECTION_ERROR_XML = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" errors="1"
failures="0" skipped="0" tests="1"><testcase classname="" name="tests.test_main"><error message="collection failure">
tests/test_main.py:8: in &lt;module&gt;
    from main import app
src/routers/crud.py:12: in &lt;module&gt;
    def list_tasks(body: schemas.TaskCreate):
E   NameError: name 'schemas' is not defined</error></testcase></testsuite></testsuites>"""

_RESULTS_XML = """<testsuites><testsuite tests="4"><testcase name="a"/><testcase name="b"/>
<testcase name="c"><failure message="assert 500 == 200">E   assert 500 == 200</failure></testcase>
<testcase name="d"><error message="failed on setup">E   sqlite3.OperationalError: no such table</error></testcase>
</testsuite></testsuites>"""


# ── parsing ─────────────────────────────────────────────────────────────────

def test_collection_error_is_named_not_read_as_zero_tests():
    out = pytest_report.parse_run(2, "collected 0 items / 1 error", _COLLECTION_ERROR_XML)
    assert out["collection_error"] == "NameError: name 'schemas' is not defined"
    assert out["passed"] == 0 and out["failed"] == 0


def test_junit_counts_failures_and_setup_errors_as_failed():
    out = pytest_report.parse_run(1, "collected 4 items", _RESULTS_XML)
    assert (out["passed"], out["failed"], out["collected"], out["collection_error"]) == (2, 2, 4, None)


def test_exit_code_5_is_no_tests_collected():
    assert pytest_report.parse_run(5, "collected 0 items", None)["collection_error"] == "no tests collected"


def test_without_a_report_the_summary_line_is_read():
    text = "collected 3 items\n...\n==== 2 passed, 1 failed in 0.4s ===="
    assert pytest_report.parse_run(1, text, None)["passed"] == 2
    coll = "ERROR collecting tests/test_main.py\nE   ModuleNotFoundError: No module named 'stripe'\n1 error"
    assert pytest_report.parse_run(2, coll, None)["collection_error"] == "ModuleNotFoundError: No module named 'stripe'"


def test_a_report_with_a_dtd_is_not_trusted():
    evil = '<!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite><testcase name="t"/></testsuite>'
    out = pytest_report.parse_run(1, "collected 1 item\n1 failed", evil)
    assert out["passed"] == 0 and out["failed"] == 1                      # fell back to the output


# ── order: import check (+ repair) first, then pytest on the repaired code ───

def _project(tmp_path, crud="import models\n"):
    src = tmp_path / "proj" / "src"
    (src / "routers").mkdir(parents=True)
    (src / "main.py").write_text("app = None\n")
    (src / "routers" / "crud.py").write_text(crud)
    return src


def _fake_exec(calls, src, import_results, junit_xml, pytest_rc):
    async def run(argv, *, cwd, project=None, env=None, timeout=None, network=False, text=False):
        if "-c" in argv:
            calls.append(("import", (src / "routers" / "crud.py").read_text()))
            rc, err = import_results.pop(0)
            return subprocess.CompletedProcess(argv, rc, "IMPORT_OK" if rc == 0 else "", err)
        calls.append(("pytest", (src / "routers" / "crud.py").read_text()))
        junit = next(a.split("=", 1)[1] for a in argv if a.startswith("--junitxml="))
        if junit_xml:
            Path(junit).write_text(junit_xml)
        return subprocess.CompletedProcess(argv, pytest_rc, "collected 1 item", "")
    return run


def _run_p07a(monkeypatch, tmp_path, src, import_results, junit_xml, pytest_rc, repair=None):
    calls = []
    monkeypatch.setattr(p07a.phase_exec, "run", _fake_exec(calls, src, import_results, junit_xml, pytest_rc))

    async def fake_repair(src_dir, error_text):
        if repair is None:
            return False
        (src_dir / "routers" / "crud.py").write_text(repair)
        return True
    monkeypatch.setattr(p07a, "repair_crud", fake_repair)
    pi = SimpleNamespace(input_data={"canonical_src_dir": str(src), "entities": []})
    return asyncio.run(p07a.run(pi, [], tmp_path / "out")), calls


def test_pytest_runs_after_the_import_repair_on_the_patched_file(monkeypatch, tmp_path):
    src = _project(tmp_path, crud="x = schemas.A\n")
    ok_xml = '<testsuite><testcase name="test_health"/><testcase name="test_app_exists"/></testsuite>'
    res, calls = _run_p07a(monkeypatch, tmp_path, src,
                           [(1, "NameError: name 'schemas' is not defined (routers/crud.py)"), (0, "")],
                           ok_xml, 0, repair="import schemas\nx = schemas.A\n")
    assert [c[0] for c in calls] == ["import", "import", "pytest"]
    assert calls[-1][1].startswith("import schemas")                        # pytest saw the repaired crud.py
    assert res.success and res.metadata["passed"] == 2 and res.metadata["exec_validation"]["fixed"]


def test_an_app_that_does_not_import_fails_the_phase_with_the_reason(monkeypatch, tmp_path):
    src = _project(tmp_path, crud="x = schemas.A\n")
    tb = ("Traceback (most recent call last):\n  File \"src/routers/crud.py\", line 1\n"
          "NameError: name 'schemas' is not defined")
    res, _ = _run_p07a(monkeypatch, tmp_path, src, [(1, tb)], _COLLECTION_ERROR_XML, 2)
    assert res.success is False
    assert res.metadata["collection_error"] == "app import failed: NameError: name 'schemas' is not defined"
    assert res.metadata["passed"] == 0 and res.metadata["failed"] == 0
    assert any(i.startswith("collection error: app import failed") for i in res.issues)


def test_s06_gate_names_the_collection_error():
    unit = {"unit_testing": s06.TaskResult("t.py", 0.2, metadata={
        "passed": 0, "failed": 0, "test_file": "t.py", "collection_error": "NameError: name 'schemas' is not defined"})}
    consolidated = s06._consolidate_results(unit, [])
    consolidated["gate"] = s06._gate_report(consolidated)
    gate = asyncio.run(s06.TestingStageSupervisor().validate_gate(
        s06.TaskResult("c.json", 0.3, metadata=consolidated), SimpleNamespace()))
    assert not gate.passed
    assert gate.issues == ["no unit test ran: collection error: NameError: name 'schemas' is not defined"]


def test_first_error_prefers_the_named_exception():
    text = "E   in <module>\nE   NameError: name 'schemas' is not defined\n"
    assert pytest_report.first_error(text) == "NameError: name 'schemas' is not defined"
    assert re.match(r"no output", pytest_report.first_error(""))


# ── the report lives in a sandbox-writable dir: no link following, bounded read ──

def _run_with_planted_report(monkeypatch, tmp_path, plant):
    src = _project(tmp_path)

    async def run(argv, *, cwd, project=None, env=None, timeout=None, network=False, text=False):
        if "-c" in argv:
            return subprocess.CompletedProcess(argv, 0, "IMPORT_OK", "")
        plant(Path(next(a.split("=", 1)[1] for a in argv if a.startswith("--junitxml="))))
        return subprocess.CompletedProcess(argv, 0, "collected 1 item\n1 passed", "")
    monkeypatch.setattr(p07a.phase_exec, "run", run)
    pi = SimpleNamespace(input_data={"canonical_src_dir": str(src), "entities": []})
    return asyncio.run(p07a.run(pi, [], tmp_path / "out"))


def test_a_junit_symlink_to_a_host_file_is_not_read(monkeypatch, tmp_path):
    host = tmp_path / "host_secret.xml"
    host.write_text('<testsuite><testcase name="a"/><testcase name="b"/><testcase name="c"/></testsuite>')
    res = _run_with_planted_report(monkeypatch, tmp_path, lambda j: j.symlink_to(host))
    assert res.metadata["passed"] == 1          # from the pytest output, not the 3 tests of the linked file


def test_an_oversized_junit_report_is_not_read(monkeypatch, tmp_path, caplog):
    big = '<testsuite>' + '<testcase name="t"/>' * (pytest_report.MAX_REPORT // 20 + 10) + '</testsuite>'
    res = _run_with_planted_report(monkeypatch, tmp_path, lambda j: j.write_text(big))
    assert res.metadata["passed"] == 1 and "larger than" in caplog.text


def test_summary_write_does_not_follow_a_planted_link(monkeypatch, tmp_path):
    host = tmp_path / "host_file"
    host.write_text("keep")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "pytest_output.txt").symlink_to(host)
    import pytest

    from aether_os.core.errors import SandboxViolation
    with pytest.raises(SandboxViolation):         # refused: s06 then reports the unit layer as failed
        _run_with_planted_report(monkeypatch, tmp_path, lambda j: None)
    assert host.read_text() == "keep"
