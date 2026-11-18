"""KAN-50: one trace id on every log line, and no secrets or personal data in the output."""
import io
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import aether_os.core.logging_config as lc
from aether_os.core.security.redact import redact_pii
from aether_os.core.telemetry.trace_context import TraceIdMiddleware, current_trace_id, new_trace_id


@pytest.fixture
def json_logs(monkeypatch):
    """configure_logging() in production mode, writing to a buffer."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    buf = io.StringIO()
    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    lc.configure_logging()
    root.handlers[0].setStream(buf)
    yield buf
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])


def lines(buf):
    return [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]


def test_secrets_and_personal_data_are_masked_in_json_logs(json_logs):
    logging.getLogger("t").warning(
        "login failed for jane.doe@example.com phone +91 98765 43210 key sk-ant-api03-abcdefghijklmnopqrstuvwx "
        "url postgresql://aether:hunter2pw@db:5432/x")
    out = json_logs.getvalue()
    for leaked in ("jane.doe@example.com", "98765 43210", "sk-ant-api03", "hunter2pw"):
        assert leaked not in out
    assert "[email]" in out and "[phone]" in out


def test_exception_text_is_redacted_too(json_logs):
    try:
        raise RuntimeError("connect failed password=SuperSecret99 for bob@corp.io")
    except RuntimeError:
        logging.getLogger("t").exception("boom")
    out = json_logs.getvalue()
    assert "SuperSecret99" not in out and "bob@corp.io" not in out


def test_ids_and_timestamps_survive_redaction(json_logs):
    tid = new_trace_id()
    from aether_os.core.telemetry.trace_context import bind_trace_id, reset_trace_id
    tok = bind_trace_id(tid)
    try:
        logging.getLogger("t").info("run 20261115-123456789012 started")
    finally:
        reset_trace_id(tok)
    rec = lines(json_logs)[0]
    assert rec["trace_id"] == tid
    assert rec["timestamp"][:4].isdigit() and "[phone]" not in rec["timestamp"]


def test_redact_pii_leaves_dates_and_short_numbers_alone():
    assert redact_pii("at 2026-11-15 14:03:11 took 12345 ms") == "at 2026-11-15 14:03:11 took 12345 ms"
    assert redact_pii("call 9876543210 now") == "call [phone] now"


def test_middleware_accepts_a_sane_id_replaces_a_hostile_one_and_echoes_it():
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)

    @app.get("/x")
    def x():
        return {"trace_id": current_trace_id()}

    c = TestClient(app)
    ok = c.get("/x", headers={"X-Trace-Id": "abc12345-def"})
    assert ok.json()["trace_id"] == "abc12345-def" and ok.headers["x-trace-id"] == "abc12345-def"
    bad = c.get("/x", headers={"X-Trace-Id": "x\ninjected"})
    assert bad.json()["trace_id"] != "x\ninjected" and len(bad.headers["x-trace-id"]) == 32
    assert current_trace_id() is None                    # not leaked past the request


def test_the_gateway_answers_with_a_trace_id_and_velaris_calls_carry_it(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from aether_os.core.telemetry.trace_context import bind_trace_id, reset_trace_id
    from aether_os.core.velaris.client import Identity, sign_request
    from aether_os.tests.gateway_env import gateway_env

    with gateway_env(tmp_path) as gw:
        r = gw.client.get("/healthz", headers={"X-Trace-Id": "browser-trace-0001"})
        assert r.headers["x-trace-id"] == "browser-trace-0001"
    tok = bind_trace_id("browser-trace-0001")
    try:
        h = sign_request(b"s" * 32, Ed25519PrivateKey.generate(), Identity("u", "o", "admin"), "GET", "/agents", b"")
    finally:
        reset_trace_id(tok)
    assert h["X-Trace-Id"] == "browser-trace-0001"
    assert "X-Trace-Id" not in sign_request(b"s" * 32, Ed25519PrivateKey.generate(), Identity("u", "o", "admin"), "GET", "/", b"")
