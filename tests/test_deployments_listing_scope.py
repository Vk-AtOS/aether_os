"""KAN-69 F7: GET /factory/deployments listed every organisation's app containers (`docker ps` is daemon wide)."""
import subprocess
from types import SimpleNamespace


def test_deployments_show_only_the_callers_containers(gw, monkeypatch):
    a, b = gw.register("depA"), gw.register("depB")
    for org, rid in ((a.org_id, "aaaaaaaa-1"), (b.org_id, "bbbbbbbb-2")):
        gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
               "VALUES (?, ?, 'x', 'completed', 1, 0, 1)", (rid, org))
    out = "aetheros-app-aaaaaaaa\t0.0.0.0:9001->8000/tcp\tUp\naetheros-app-bbbbbbbb\t0.0.0.0:9002->8000/tcp\tUp\n"
    monkeypatch.setattr(subprocess, "run", lambda *a_, **k: SimpleNamespace(stdout=out, returncode=0))
    r = gw.client.get("/factory/deployments", headers=a.auth)
    assert r.status_code == 200, r.text
    assert [c["name"] for c in r.json()["containers"]] == ["aetheros-app-aaaaaaaa"]
