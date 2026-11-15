"""KAN-100 p07c: a scan that did not run, or that errored, is not a pass; the script really counts violations."""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from aether_os.phases.p07c_accessibility_testing import task_agent


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<html></html>")

    def log_message(self, *a):
        pass


@pytest.fixture()
def frontend():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _run(tmp_path, monkeypatch, url, node_out):
    class Proc:
        async def communicate(self):
            return node_out.encode(), b""

    async def fake_exec(*a, **k):
        return Proc()
    monkeypatch.setattr(task_agent.asyncio, "create_subprocess_exec", fake_exec)
    r = asyncio.run(task_agent.run(SimpleNamespace(input_data={"frontend_url": url}), [], tmp_path))
    return json.loads((tmp_path / "a11y_results.json").read_text()), r


def test_scan_that_errors_or_cannot_run_is_not_a_pass(tmp_path, monkeypatch, frontend):
    res, _ = _run(tmp_path, monkeypatch, frontend, json.dumps({"error": "browser crashed"}))
    assert res["passed"] is False and res.get("skipped") is True
    res, _ = _run(tmp_path / "b", monkeypatch, "http://127.0.0.1:9", "")
    assert res["passed"] is False


def test_scan_with_violations_fails_and_clean_scan_passes(tmp_path, monkeypatch, frontend):
    res, _ = _run(tmp_path, monkeypatch, frontend, json.dumps({"violations": 2, "passes": 5, "incomplete": 0, "items": []}))
    assert res["passed"] is False and res["violations"] == 2
    res, _ = _run(tmp_path / "c", monkeypatch, frontend, json.dumps({"violations": 0, "passes": 9, "incomplete": 0, "items": []}))
    assert res["passed"] is True


def test_axe_script_does_not_swallow_violations():
    # checkA11y(page, ctx, opts, skipFailures=true) never throws, which made every scan report 0 violations
    assert "checkA11y" not in task_agent._AXE_SCRIPT and "axe.run(" in task_agent._AXE_SCRIPT


def test_section_508_rules_are_injected_for_domains_whose_pack_requires_them(tmp_path, monkeypatch, frontend):
    assert "section508" in task_agent.axe_tags_for("govtech") and "section508" in task_agent.axe_tags_for("edtech")
    assert task_agent.axe_tags_for("crm") == task_agent._BASE_AXE_TAGS
    seen = {}

    class Proc:
        async def communicate(self):
            return json.dumps({"violations": 0, "passes": 1, "incomplete": 0, "items": []}).encode(), b""

    async def fake_exec(*a, **k):
        seen["args"] = a
        return Proc()
    monkeypatch.setattr(task_agent.asyncio, "create_subprocess_exec", fake_exec)
    asyncio.run(task_agent.run(SimpleNamespace(input_data={"frontend_url": frontend, "domain": "govtech"}), [], tmp_path))
    assert "section508" in json.loads(seen["args"][-1])
    assert "Section 508" in json.loads((tmp_path / "a11y_results.json").read_text())["wcag_level"]
