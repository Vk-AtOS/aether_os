"""KAN-161: GET /factory/runs/{id}/test-report returns the unit-test phase's result (nothing writes runs.self_test_report)."""
import json
import pathlib


def _run(gw, org, rid):
    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
           "VALUES (?, ?, 'x', 'completed', 0, 0, 1)", (rid, org.org_id))


def test_report_comes_from_the_phase_summary_and_is_tenant_scoped(gw, tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    org, other = gw.register("treport"), gw.register("treportb")
    _run(gw, org, "trun-1")
    assert gw.client.get("/factory/runs/trun-1/test-report", headers=org.auth).status_code == 404
    out = tmp_path / ".aether_os" / "projects" / "trun-1" / "p07a_unit_testing" / "unit"
    out.mkdir(parents=True)
    (out / "summary.json").write_text(json.dumps({"tests_written": 4, "passed": 3, "failed": 1, "errors": ["boom"]}))
    got = gw.client.get("/factory/runs/trun-1/test-report", headers=org.auth).json()
    assert (got["passed"], got["failed"], got["errors"]) == (3, 1, ["boom"])
    assert gw.client.get("/factory/runs/trun-1/test-report", headers=other.auth).status_code == 404
