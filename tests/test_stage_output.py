"""GET /factory/runs/{id} serves stage-keyed output for all 12 stages, and /events can drop llm_chunk."""
from __future__ import annotations

import json
import time
import uuid

import pytest

import aether_os.core.projects as projects_mod
from aether_os.gateway.services.phase_output import STAGE_FOLDERS, enrich_phases
from aether_os.orchestrator.phase_sequence import PHASE_SEQUENCE


def test_mapping_covers_exactly_the_twelve_stages_and_each_stage_folder_comes_first():
    assert list(STAGE_FOLDERS) == list(PHASE_SEQUENCE) and len(STAGE_FOLDERS) == 12
    for stage, folders in STAGE_FOLDERS.items():
        assert folders[0] == stage and len(folders) >= 1


def test_every_stage_with_artifacts_gets_output(tmp_path):
    """One artifact in each stage's real legacy folder: with JSON for some, only source files for others."""
    phases = {stage: {"status": "passed"} for stage in PHASE_SEQUENCE}
    for i, (stage, folders) in enumerate(STAGE_FOLDERS.items()):
        legacy = folders[1] if len(folders) > 1 else folders[0]
        base = tmp_path / legacy
        base.mkdir()
        if i % 2:
            (base / "summary.json").write_text(json.dumps({"stage": stage, "path": f"{tmp_path}/x"}))
        else:
            (base / "src").mkdir()
            (base / "src" / "main.py").write_text("x = 1\n")
    out = enrich_phases(phases, tmp_path, str(tmp_path) + "/")
    for i, stage in enumerate(PHASE_SEQUENCE):
        assert out[stage].get("output"), f"{stage} has artifacts but no output"
        if i % 2:
            assert out[stage]["output"]["stage"] == stage and out[stage]["output"]["path"] == "x"   # server path stripped
            assert out[stage]["output_file"].endswith("summary.json")
        else:
            assert out[stage]["output"]["file_count"] == 1 and "output_file" not in out[stage]


def test_stage_own_summary_wins_over_sub_phase_folders(tmp_path):
    (tmp_path / "s02_architecture").mkdir()
    (tmp_path / "s02_architecture" / "s02_architecture.json").write_text('{"own": true}')
    (tmp_path / "p02_architecture").mkdir()
    (tmp_path / "p02_architecture" / "architecture.json").write_text('{"own": false}')
    out = enrich_phases({"s02_architecture": {}}, tmp_path, "/nope/")
    assert out["s02_architecture"]["output"] == {"own": True}


def test_stage_with_no_artifacts_has_no_output(tmp_path):
    assert "output" not in enrich_phases({"s10_enterprise": {}}, tmp_path, "/x/")["s10_enterprise"]


def test_security_findings_attach_to_the_quality_stage_and_to_the_legacy_key(tmp_path):
    report = tmp_path / "p06_review_security" / "security"
    report.mkdir(parents=True)
    (report / "security_report.json").write_text(json.dumps({"findings": [{"id": "B101"}], "total": 1}))
    out = enrich_phases({"s05_quality": {}, "p06_review_security": {}}, tmp_path, "/x/")
    for key in ("s05_quality", "p06_review_security"):
        assert out[key]["output"]["security_findings"] == [{"id": "B101"}] and out[key]["output"]["security_total"] == 1


# ── through the real endpoints ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def projects_root(tmp_path_factory):
    saved = projects_mod._manager
    root = tmp_path_factory.mktemp("stageprojects")
    projects_mod._manager = projects_mod.ProjectManager(root=root)
    yield root
    projects_mod._manager = saved


def test_run_detail_serves_stage_keyed_output(gw, projects_root):
    owner = gw.register("stageout")
    run_id = str(uuid.uuid4())
    gw.sql("INSERT INTO runs (id, org_id, command, raw_input, status, started_at, cost, run_version) "
           "VALUES (?, ?, 'factory: x', 'x', 'completed', ?, 0, 1)", (run_id, owner.org_id, time.time()))
    for stage in ("s03_backend", "s05_quality"):
        gw.sql("INSERT INTO phase_completions (run_id, phase_name, status, updated_at) VALUES (?, ?, 'passed', ?)",
               (run_id, stage, time.time()))
    backend = projects_root / run_id / "p04_backend" / "backend_codegen"
    backend.mkdir(parents=True)
    (backend / "api_routes.json").write_text('{"routes": 3}')
    sec = projects_root / run_id / "p06_review_security" / "security"
    sec.mkdir(parents=True)
    (sec / "security_report.json").write_text(json.dumps({"findings": [{"id": "B1"}], "total": 1}))

    body = gw.client.get(f"/factory/runs/{run_id}", headers=owner.auth).json()
    assert body["phases"]["s03_backend"]["output"]["file_count"] >= 1
    assert body["phases"]["s05_quality"]["output"]["security_total"] == 1
    assert str(projects_root) not in json.dumps(body["phases"])


def test_events_can_exclude_llm_chunk(gw, projects_root):
    owner = gw.register("evexcl")
    run_id = str(uuid.uuid4())
    gw.sql("INSERT INTO runs (id, org_id, command, raw_input, status, started_at, cost, run_version) "
           "VALUES (?, ?, 'factory: x', 'x', 'completed', ?, 0, 1)", (run_id, owner.org_id, time.time()))
    for kind in ("llm_chunk", "llm_chunk", "phase_complete", "pipeline_complete"):
        gw.sql("INSERT INTO pipeline_events (id, run_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
               (str(uuid.uuid4()), run_id, kind, json.dumps({"type": kind, "phase": "s01_intake"})))
    everything = gw.client.get(f"/factory/runs/{run_id}/events", headers=owner.auth).json()
    assert everything["total"] == 4
    slim = gw.client.get(f"/factory/runs/{run_id}/events?exclude=llm_chunk", headers=owner.auth).json()
    assert {e["event_type"] for e in slim["events"]} == {"phase_complete", "pipeline_complete"}
    two = gw.client.get(f"/factory/runs/{run_id}/events?exclude=llm_chunk,phase_complete", headers=owner.auth).json()
    assert [e["event_type"] for e in two["events"]] == ["pipeline_complete"]
    assert gw.client.get(f"/factory/runs/{run_id}/events?exclude=llm_chunk",
                         headers=gw.register("evother").auth).status_code == 404


def test_the_dashboard_asks_for_events_without_llm_chunk():
    from pathlib import Path
    api = (Path(__file__).resolve().parent.parent / "dashboard" / "src" / "api.js").read_text()
    assert "exclude: 'llm_chunk'" in api
