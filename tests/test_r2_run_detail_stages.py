"""KAN-185/KAN-170: the run detail payload shows failed and skipped stages and the council verdict."""
import time
import uuid

import pytest
import yaml

from aether_os.orchestrator.stage_gate import council_view


def test_council_view_never_calls_a_missing_verdict_approved():
    assert council_view(None) == {"council_verdict": None, "council_score": None}
    assert council_view({"status": "unavailable", "passed": None})["council_verdict"] == "unavailable"
    assert council_view({"passed": True, "score": 0.9}) == {"council_verdict": "approved", "council_score": 90}
    assert council_view({"passed": False, "score": 0.3})["council_verdict"] == "rejected"


def test_run_detail_lists_failed_and_skipped_stages_and_council(gw):
    u = gw.register("stagesorg")
    rid = str(uuid.uuid4())
    gw.sql("INSERT INTO runs (id, org_id, status, started_at, cost, run_version, council_delivery) VALUES (?,?,?,?,0,1,?)",
           (rid, u.org_id, "completed", time.time(), '{"status": "unavailable", "passed": null}'))
    for name, status in (("s05_quality", "passed"), ("s06_testing", "failed"), ("s08_observability", "skipped")):
        gw.sql("INSERT INTO phase_completions (run_id, phase_name, status, updated_at) VALUES (?,?,?,?)",
               (rid, name, status, time.time()))
    body = gw.client.get(f"/factory/runs/{rid}", headers=u.auth).json()
    ss = body["stage_summary"]
    assert [f["stage"] for f in ss["failed_stages"]] == ["s06_testing"]
    assert [s["stage"] for s in ss["skipped_stages"]] == ["s08_observability"]
    assert ss["all_stages_ok"] is False
    assert body["council_verdict"] == "unavailable"


def test_env_templates_default_the_council_to_strict():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    assert "COUNCIL_STRICT_MODE=true" in (root / ".env.example").read_text()
    assert yaml.safe_load((root / "helm/aetheros/values.yaml").read_text())["config"]["COUNCIL_STRICT_MODE"] == "true"
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    assert any(svc.get("environment", {}).get("COUNCIL_STRICT_MODE") == "true" for svc in compose["services"].values())
