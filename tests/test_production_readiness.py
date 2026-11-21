"""KAN-53: the readiness script runs, never reports an owner-only item as PASS, and fails when evidence is missing."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("production_readiness", ROOT / "scripts/production_readiness.py")
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)


def test_no_blocker_fails_and_owner_items_stay_unverified():
    rows = {r["item"]: r["status"] for r in pr.run()}
    # Update this set when a blocker is fixed or a new one is found: the checklist must never go quiet by accident.
    # "sandbox isolation" left this set when the API stopped mounting the Docker socket (docker-proxy, KAN-65/66/101).
    assert {k for k, v in rows.items() if v == "FAIL"} == set()
    assert rows["sandbox isolation"] == "PASS"
    assert rows["access reviews"] == rows["incident contacts"] == rows["restore on real data"] == "UNVERIFIED"


def test_missing_evidence_fails_and_a_crashing_check_is_a_fail(monkeypatch):
    monkeypatch.setattr(pr, "ROOT", ROOT / "does-not-exist")
    assert pr.backups()[0] == "FAIL"
    monkeypatch.setitem(pr.CHECKS, "boom", lambda: 1 / 0)
    assert [r for r in pr.run() if r["item"] == "boom"][0]["status"] == "FAIL"
    assert pr.main([]) == 1


def test_live_probe_of_an_unreachable_host_fails_not_skips():
    rows = pr.live("http://127.0.0.1:1")
    assert rows["live /healthz"][0] == "FAIL" and rows["live TLS"][0] == "FAIL"
