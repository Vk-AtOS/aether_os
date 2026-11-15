"""KAN-187: the generated SSE stream is proxy-safe (headers, heartbeat) and ends by itself."""
import sys
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aether_os.phases.p04a_backend_codegen.helpers_sse import _generate_sse_router


def test_generated_stream_has_proxy_headers_a_heartbeat_and_a_bounded_lifetime(monkeypatch):
    auth = types.ModuleType("auth")
    auth.get_current_user = lambda: {"id": "u1", "org_id": "o1"}
    monkeypatch.setitem(sys.modules, "auth", auth)
    monkeypatch.setenv("SSE_MAX_SECONDS", "0")
    ns = {"__name__": "realtime_router"}
    exec(compile(_generate_sse_router(["chat"], "Demo"), "realtime_router.py", "exec"), ns)
    app = FastAPI()
    app.include_router(ns["realtime_router"])
    r = TestClient(app).get("/realtime/stream")
    assert r.headers["x-accel-buffering"] == "no" and r.headers["cache-control"] == "no-cache"
    assert r.text.startswith(": connected\n\n") and "event: stream_limit" in r.text    # ended by itself
