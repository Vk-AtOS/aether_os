"""KAN-100 / KAN-99 p07c: a scan that did not run, or that errored, is not a pass; axe runs in the browser sandbox."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from aether_os.core.sandbox.runner import SandboxUnavailable
from aether_os.phases.p07c_accessibility_testing import gate, task_agent


@pytest.fixture()
def project(tmp_path):
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>")
    return tmp_path, dist


def _run(tmp_path, monkeypatch, dist, reply, domain="", seen=None):
    async def fake_job(job, *, project, timeout=120):
        if seen is not None:
            seen.append(job)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(task_agent, "run_browser_job", fake_job)
    out = tmp_path / "out"
    data = {"frontend_dist_dir": str(dist), "domain": domain}
    r = asyncio.run(task_agent.run(SimpleNamespace(input_data=data), [], out))
    return json.loads((out / "a11y_results.json").read_text()), r


def test_without_a_build_the_phase_is_deferred(tmp_path):
    out = tmp_path / "o"
    r = asyncio.run(task_agent.run(SimpleNamespace(input_data={"frontend_url": "http://localhost:5173"}), [], out))
    assert r.metadata["skipped"] is True       # a URL cannot be reached from the no-network sandbox


def test_scan_that_errors_or_cannot_run_is_not_a_pass(project, monkeypatch):
    tmp_path, dist = project
    res, _ = _run(tmp_path, monkeypatch, dist, {"ok": False, "error": "browser crashed"})
    assert res["passed"] is False and res.get("skipped") is True
    res, _ = _run(tmp_path, monkeypatch, dist, SandboxUnavailable("no docker"))
    assert res["passed"] is False and "unavailable" in res["reason"]


def test_scan_with_violations_fails_and_clean_scan_passes(project, monkeypatch):
    tmp_path, dist = project
    res, _ = _run(tmp_path, monkeypatch, dist, {"ok": True, "violations": 2, "passes": 5, "incomplete": 0, "items": []})
    assert res["passed"] is False and res["violations"] == 2
    res, _ = _run(tmp_path, monkeypatch, dist, {"ok": True, "violations": 0, "passes": 9, "incomplete": 0, "items": []})
    assert res["passed"] is True


def test_the_job_serves_dist_on_the_sandbox_loopback_and_counts_via_axe_run(project, monkeypatch):
    import pathlib
    src = (pathlib.Path(task_agent.__file__).parents[2] / "core/sandbox/browser/entry.py").read_text()
    assert "axe.run(" in src and "checkA11y" not in src           # never a helper that cannot throw
    tmp_path, dist = project
    seen = []
    _run(tmp_path, monkeypatch, dist, {"ok": True, "violations": 0, "passes": 1, "incomplete": 0, "items": []}, seen=seen)
    job = seen[0]
    assert job["action"] == "axe" and job["serve"]["dir"] == str(dist) and job["url"].startswith("http://127.0.0.1:")


def test_section_508_rules_are_injected_for_domains_whose_pack_requires_them(project, monkeypatch):
    assert "section508" in task_agent.axe_tags_for("govtech") and "section508" in task_agent.axe_tags_for("edtech")
    assert task_agent.axe_tags_for("crm") == task_agent._BASE_AXE_TAGS
    tmp_path, dist = project
    seen = []
    res, _ = _run(tmp_path, monkeypatch, dist, {"ok": True, "violations": 0, "passes": 1, "incomplete": 0, "items": []},
                  domain="govtech", seen=seen)
    assert "section508" in seen[0]["tags"] and "Section 508" in res["wcag_level"]


def test_gate_reads_the_findings_from_items_when_violations_is_a_count(tmp_path):
    """The result stores a count; the gate iterated it as a list and always reported 'could not parse'."""
    f = tmp_path / "a11y_results.json"
    items = [{"id": f"r{i}", "impact": "critical"} for i in range(4)]
    f.write_text(json.dumps({"violations": 4, "items": items}))
    out = gate.validate(SimpleNamespace(output_path=str(f)))
    assert out.passed is False and any("critical" in i for i in out.issues) and not any("parse" in i for i in out.issues)
