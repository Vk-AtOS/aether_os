"""KAN-243: the rule packs gate every run. The clean export of a run is scanned; a blocking finding in a model-written
file goes back to the model (at most 3 rounds), one in a template file fails the run as a platform bug, and s11 fails
when the gate does. The task tracker template set itself must have no blocking finding."""
from __future__ import annotations

import asyncio
import json
import shutil
from types import SimpleNamespace

import pytest

from aether_os.core.rulepacks import pipeline_gate as pg
from aether_os.core.rulepacks.provenance import load_model_files, record_model_files, write_model_file
from aether_os.phases.base import TaskResult
from aether_os.stages.s11_handoff.supervisor import HandoffStageSupervisor
from aether_os.tests.rulepacks_sample_run import build_tracker_workspace

PAGE = "src/pages/TaskPage.tsx"


@pytest.fixture(scope="module")
def tracker_ws(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        return build_tracker_workspace(tmp_path_factory.mktemp("tracker"), mp)


@pytest.fixture
def ws(tracker_ws, tmp_path):
    dst = tmp_path / "run"
    shutil.copytree(tracker_ws, dst)
    return dst


async def _no_repair(app_root, rel, errors):
    raise AssertionError(f"nothing model-written should be repaired, got {rel}")


def _gate(ws, tmp_path, repair=_no_repair, routes=None):
    return asyncio.run(pg.run_rulepacks_gate(ws, tmp_path / "s11", "tracker",
                                             routes if routes is not None else pg.spec_public_routes({}), repair=repair))


def test_tracker_template_set_has_no_blocking_finding(ws, tmp_path):
    # Before KAN-243/KAN-267 the templates shipped 3: the demo seed ran at every production start (PRD-013), Alembic had
    # no revision so `alembic upgrade head` created nothing (PRD-003), and the platform never declared POST /auth/logout
    # public (SEC-007).
    res = _gate(ws, tmp_path)
    blocking = [f for pack in res.report["findings"].values() for f in pack if f["severity"] in ("high", "critical")]
    assert blocking == [] and res.passed and res.ran, blocking
    saved = json.loads((tmp_path / "s11" / pg.REPORT_FILE).read_text())
    assert saved["counts"]["high"] == saved["counts"]["critical"] == 0 and saved["repair_rounds"] == 0


def test_blocking_finding_in_a_template_file_fails_and_names_rule_and_file(ws, tmp_path):
    stats = ws / "p04_backend" / "backend_codegen" / "src" / "routers" / "stats.py"
    stats.write_text(stats.read_text() + "\n\ndef _run(expr: str):\n    return eval(expr)\n")
    res = _gate(ws, tmp_path)                       # _no_repair: a template is never sent to the model
    assert not res.passed and "platform bug" in res.reason
    assert "SEC-005" in res.reason and "backend/src/routers/stats.py" in res.reason
    assert res.report["template_blocking"] and not res.report["model_blocking"]


def _inject_xss(ws):
    page = ws / "frontend" / PAGE
    page.write_text(page.read_text().replace("return (", "return (<div dangerouslySetInnerHTML={{ __html: String(location.hash) }} />) || (", 1))
    record_model_files(ws / "frontend", [PAGE])


def test_blocking_finding_in_a_model_file_is_repaired_and_rescanned(ws, tmp_path):
    _inject_xss(ws)
    calls = []

    async def fix(app_root, rel, errors):
        calls.append((rel, errors))
        p = app_root / rel
        p.write_text(p.read_text().replace("<div dangerouslySetInnerHTML={{ __html: String(location.hash) }} />", "null"))
        return True
    res = _gate(ws, tmp_path, repair=fix)
    assert res.passed and res.rounds == 1 and res.repaired == ["frontend/" + PAGE]
    assert calls[0][0] == PAGE and "SEC-015" in calls[0][1] and f"`{PAGE}`" in calls[0][1]   # repair_prompt text


def test_model_file_still_failing_after_three_rounds_blocks(ws, tmp_path):
    _inject_xss(ws)
    rounds = []

    async def useless(app_root, rel, errors):
        rounds.append(rel)
        return False
    res = _gate(ws, tmp_path, repair=useless)
    assert len(rounds) == pg.MAX_ROUNDS == res.rounds
    assert not res.passed and "after 3 repair round(s)" in res.reason and "SEC-015" in res.reason
    assert "frontend/" + PAGE in res.reason and "platform bug" not in res.reason


def test_default_repair_sends_repair_prompt_through_the_patch_path_and_may_change_only_that_file(ws, tmp_path, monkeypatch):
    _inject_xss(ws)
    prompts = []

    async def fake_patches(prompt, tag, timeout=90.0):
        prompts.append(prompt)
        return [{"file": PAGE, "find": "<div dangerouslySetInnerHTML={{ __html: String(location.hash) }} />", "replace": "null"},
                {"file": "src/lib/api.ts", "find": "const API_PREFIX = '/api'", "replace": "const API_PREFIX = ''"}]
    monkeypatch.setattr(pg, "request_patches", fake_patches)
    api_before = (ws / "frontend" / "src" / "lib" / "api.ts").read_text()
    res = _gate(ws, tmp_path, repair=pg.model_repair)
    assert res.passed and len(prompts) == 1 and "SEC-015" in prompts[0] and f"--- {PAGE}" in prompts[0]
    assert (ws / "frontend" / "src" / "lib" / "api.ts").read_text() == api_before      # the other patch was rejected


def test_spec_public_routes_add_to_the_platform_ones():
    assert pg.spec_public_routes({"public_routes": ["GET /products/*", 3]})[-1] == "GET /products/*"
    assert "POST /auth/logout" in pg.spec_public_routes({})


def test_write_model_file_records_the_path_relative_to_the_app(tmp_path):
    app = tmp_path / "frontend"
    (app / "src" / "pages").mkdir(parents=True)
    (app / "package.json").write_text("{}")
    write_model_file(app / "src" / "pages" / "X.tsx", "export default function X() { return null }")
    assert load_model_files(app) == {"src/pages/X.tsx"}


def _s11_gate(metadata):
    result = TaskResult(output_path="", confidence=1.0, metadata=metadata, issues=[], success=True)
    return asyncio.run(HandoffStageSupervisor().validate_gate(result, SimpleNamespace(input_data={})))


def test_s11_gate_fails_when_the_rule_packs_block():
    blocked = _s11_gate({"rulepacks": {"blocking_reason": "platform bug ...: SEC-007 in backend/src/routers/x.py"}})
    assert not blocked.passed and "SEC-007 in backend/src/routers/x.py" in blocked.issues[0]


def test_s11_gate_keeps_its_own_decision_when_the_rule_packs_pass(tmp_path):
    for name in ("export_manifest.json", "quality_report.json"):    # what s11's own gate (KAN-247) requires
        (tmp_path / name).write_text("{}")
    own = {"export_manifest_path": str(tmp_path / "export_manifest.json"),
           "quality_report_path": str(tmp_path / "quality_report.json")}
    assert _s11_gate({**own, "rulepacks": {"blocking_reason": None, "passed": True}}).passed
    assert not _s11_gate({"rulepacks": {"blocking_reason": None, "passed": True}}).passed   # its own refusal stays


def test_s11_runs_the_gate_and_records_it(ws, tmp_path):
    issues = []
    meta = asyncio.run(pg.run_stage_gate(SimpleNamespace(input_data={"project_dir": str(ws), "project_name": "t"}),
                                         tmp_path / "s11", issues))
    assert meta["ran"] and meta["passed"] and issues == [] and meta["report_path"].endswith(pg.REPORT_FILE)
