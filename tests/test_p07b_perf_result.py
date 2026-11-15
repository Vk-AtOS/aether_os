"""KAN-109/KAN-100: a finished load test returns a TaskResult and its error rate reaches the gate."""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

from aether_os.phases.base import TaskResult
from aether_os.phases.p07b_performance_testing import gate
from aether_os.phases.p07b_performance_testing.task_agent import run


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def test_load_test_completes(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        pi = SimpleNamespace(input_data={"backend_port": srv.server_port, "entities": []})
        res = asyncio.run(run(pi, [], tmp_path))
    finally:
        srv.shutdown()
    assert isinstance(res, TaskResult) and res.success
    assert "load_test_summary" in res.metadata


def test_gate_fails_on_error_rate_pct(tmp_path):
    f = tmp_path / "perf_results.json"
    f.write_text(json.dumps({"p95_ms": 10, "error_rate_pct": 50.0}))
    out = gate.validate(TaskResult(output_path=str(f), confidence=0.8))
    assert out.passed is False


def test_latency_sla_comes_from_the_requirements_then_the_domain_then_the_default():
    from aether_os.phases.p07b_performance_testing.task_agent import _latency_sla_p95_ms as sla
    assert sla({"latency_sla_p95_ms": 300, "domain": "trading"}) == 300
    assert sla({"domain": "trading"}) == 200 and sla({"domain": "Fintech"}) == 500
    assert sla({"domain": "crm"}) == 2000 and sla({"latency_sla_p95_ms": "junk"}) == 2000
