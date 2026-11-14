"""The load harness records results in the documented format (runs against a tiny local server)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from aether_os.tests.load import harness


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"{}"):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._send(200, json.dumps({"access_token": "t"}).encode())

    def do_GET(self):
        self._send(500 if self.path.startswith("/workspaces") else 200)


def test_harness_records_result_in_documented_format(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = tmp_path / "r.json"
    code = harness.main(["--host", f"http://127.0.0.1:{srv.server_port}", "--users", "3", "--duration", "1",
                         "--email", "a", "--password", "b", "--out", str(out), "--max-error-rate", "0.5"])
    srv.shutdown()
    res = json.loads(out.read_text())
    assert res["schema_version"] == 1 and res["users"] == 3
    for k in ("requests", "errors", "error_rate", "p50_ms", "p95_ms", "p99_ms", "mean_ms", "rps"):
        assert k in res["total"]
    assert res["endpoints"]["/workspaces"]["errors"] == res["endpoints"]["/workspaces"]["requests"] > 0
    assert res["endpoints"]["/health"]["errors"] == 0
    assert code == 0


def test_percentile():
    assert harness.percentile([1, 2, 3, 4, 100], 95) == 100
    assert harness.percentile([], 50) == 0.0
