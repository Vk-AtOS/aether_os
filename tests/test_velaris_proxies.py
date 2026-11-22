"""Chat / mail / control / HR proxies against a fake Velaris (httpx MockTransport)."""
# ruff: noqa: F811,F401  (the svc fixture is imported by name)
from __future__ import annotations

import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from sqlalchemy import update

import aether_os.core.db as db
from aether_os.core.route_walk import iter_routes
from aether_os.core.audit import chain
from aether_os.core.models import User
from aether_os.core.velaris.client import VelarisClient
from aether_os.gateway import velaris_proxy
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers import (velaris_chat_router, velaris_control_router, velaris_hr_router,
                                       velaris_mail_router, velaris_providers_router)
from aether_os.tests.prime_helpers import ALICE, API_KEY, DAVE, MEMBER, ORG, OUTSIDER, OWNER, svc  # noqa: F401

pytestmark = pytest.mark.asyncio
SECRET = "x" * 40
KEY = Ed25519PrivateKey.generate()
ROUTERS = (velaris_chat_router, velaris_mail_router, velaris_control_router, velaris_hr_router,
           velaris_providers_router)
SSE = b'id: 0\nevent: message\ndata: {"id":0,"type":"message"}\n\n'


class _Stream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield SSE


class FakeVelaris:
    def __init__(self):
        self.seen, self.down = [], False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused")
        claims = json.loads(base64.urlsafe_b64decode(req.headers["x-velaris-identity"].split(".")[0] + "=="))
        self.seen.append({"method": req.method, "raw": req.url.raw_path.decode(), "claims": claims,
                          "body": req.content, "headers": dict(req.headers)})
        p = req.url.path
        if p == "/chat/events/stream":
            if "queue_id=bad" in req.url.query.decode():
                return httpx.Response(410, json={"error": {"code": "bad_queue", "message": "register again"}})
            return httpx.Response(200, stream=_Stream(), headers={"content-type": "text/event-stream"})
        if p == "/chat/files/abc":
            return httpx.Response(200, content=b"PDFBYTES", headers={
                "content-type": "application/pdf", "content-disposition": "attachment; filename*=UTF-8''a.pdf",
                "x-content-type-options": "nosniff", "set-cookie": "leak=1"})
        if p == "/chat/files":
            return httpx.Response(201, json={"sha256": "abc", "size": len(req.content)})
        if p == "/chat/channels/9":
            return httpx.Response(403, json={"error": {"code": "forbidden", "message": "no", "trace": "Traceback"}})
        if p == "/control/runs":
            return httpx.Response(202, json={"status": "waiting_approval", "run_id": "r1"})
        if p.startswith("/agents/"):
            return httpx.Response(202, json={"kind": "act", "run": {"run_id": "r2", "status": "waiting_approval"}})
        return httpx.Response(200, json={"ok": True, "path": p})


@pytest.fixture
def velaris(monkeypatch, tmp_path):
    fake = FakeVelaris()
    pem = tmp_path / "id.pem"
    pem.write_bytes(KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    monkeypatch.setenv("VELARIS_API_URL", "http://velaris.test")
    monkeypatch.setenv("VELARIS_API_SECRET", SECRET)
    monkeypatch.setenv("VELARIS_IDENTITY_PRIVATE_KEY", str(pem))
    transport = httpx.MockTransport(fake)
    monkeypatch.setattr(velaris_proxy, "_client", lambda: VelarisClient.from_env(transport=transport))
    return fake


def make_app() -> FastAPI:
    app = FastAPI()
    for m in ROUTERS:
        app.include_router(m.router)
    return app


@pytest.fixture
def http(svc, velaris):
    who = {"user": OWNER}
    app = make_app()
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    client.who = who
    return client


async def actions():
    return [e["action"] for e in await chain.read_entries(limit=1000)]


async def test_identity_is_the_user_row_not_headers_or_token(http, velaris):
    http.who["user"] = {**MEMBER, "role": "owner"}          # forged token claim
    r = await http.post("/chat/channels/5/messages", json={"body": "hi", "user_id": "mallory"},
                        headers={"X-Velaris-Identity": "forged", "X-Forwarded-User": "mallory",
                                 "X-Velaris-Signature": "forged"})
    assert r.status_code == 200
    seen = velaris.seen[-1]
    assert seen["claims"]["sub"] == DAVE and seen["claims"]["org"] == ORG and seen["claims"]["roles"] == []
    assert "forged" not in seen["headers"]["x-velaris-identity"] and "x-forwarded-user" not in seen["headers"]


async def test_viewer_may_look_but_not_act(http, velaris):
    async with db.get_session_factory()() as s:
        await s.execute(update(User).where(User.id == DAVE).values(role="viewer"))
        await s.commit()
    http.who["user"] = MEMBER
    assert (await http.post("/chat/channels/5/messages", json={"body": "x"})).status_code == 403
    assert (await http.post("/hr/ATS_CORE/pipeline", json={})).status_code == 403
    assert (await http.get("/control/tasks")).status_code == 200
    assert len(velaris.seen) == 1


async def test_api_keys_ghosts_and_strangers_are_refused(http, velaris):
    for user in (API_KEY, {"user_id": "ghost", "org_id": ORG, "role": "owner"}, {**OUTSIDER, "org_id": ORG}):
        http.who["user"] = user
        for method, path in (("GET", "/chat/channels"), ("GET", "/mail/mailboxes"), ("GET", "/control/tasks"),
                             ("POST", "/hr/ATS_CORE/pipeline")):
            assert (await http.request(method, path)).status_code == 403
    assert velaris.seen == []


async def test_every_endpoint_requires_auth(svc):
    app = make_app()
    n = 0
    for route in iter_routes(app.routes):
        if not getattr(route, "dependant", None) or not route.path.startswith(("/chat", "/mail", "/control", "/hr")):
            continue
        calls = [d.call for d in route.dependant.dependencies]
        assert get_current_user in calls, route.path
        n += 1
    assert n >= 90
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        for route in iter_routes(app.routes):
            if getattr(route, "dependant", None) and route.path.startswith(("/chat", "/mail", "/control", "/hr")):
                path = route.path.replace("{", "").replace("}", "") if "{" not in route.path else route.path
                for m in route.methods:
                    assert (await c.request(m, path.format_map(_Any()))).status_code == 401, (m, route.path)


class _Any(dict):
    def __missing__(self, key):
        return "1"


async def test_hr_allowlist_refuses_everything_else(http, velaris):
    for agent, method in (("ATS_CORE", "_private"), ("PAYROLL_ENGINE", "pay_out"), ("NOPE", "x"),
                          ("ESIGN", "open_signing"), ("ATS_CORE", "erase_candidate"), ("ats_core", "pipeline")):
        assert (await http.post(f"/hr/{agent}/{method}", json={})).status_code == 404
    assert velaris.seen == []
    # erasure exists only behind admin + typed confirmation (KAN-142/144/199): bare, it is refused unseen
    for agent, method in (("ATS_CORE", "erase_candidates"), ("EMPLOYEE_RECORDS", "erase_subject")):
        assert (await http.post(f"/hr/{agent}/{method}", json={})).status_code == 422
    assert velaris.seen == []


async def test_hr_call_passes_202_and_ledgers_names_only(http, velaris):
    r = await http.post("/hr/ATS_CORE/create_requisition", json={"title": "Secret Role", "openings": 2})
    assert r.status_code == 202 and r.json()["run"]["status"] == "waiting_approval"
    assert velaris.seen[-1]["raw"] == "/agents/ATS_CORE/create_requisition"
    assert json.loads(velaris.seen[-1]["body"]) == {"title": "Secret Role", "openings": 2}
    entries = [e for e in await chain.read_entries(limit=1000) if e["action"] == "velaris.hr.call"]
    assert [e["payload"]["phase"] for e in entries] == ["request", "result"]
    assert entries[-1]["payload"]["outcome"] == "202" and "Secret Role" not in json.dumps(entries)
    assert (await http.post("/hr/ATS_CORE/list_requisitions")).status_code == 202   # empty body -> {}
    assert velaris.seen[-1]["body"] == b"{}"


async def test_control_start_202_and_ledger(http, velaris):
    r = await http.post("/control/runs", json={"task_id": "t1", "params": {"secret": "s3cret"}})
    assert r.status_code == 202 and r.json()["status"] == "waiting_approval"
    entries = [e for e in await chain.read_entries(limit=1000) if e["action"] == "velaris.control.start"]
    assert entries[0]["payload"]["task_id"] == "t1" and "s3cret" not in json.dumps(entries)
    await http.post("/control/runs/r1/kill")
    assert "velaris.control.kill" in await actions()


async def test_velaris_down_and_unconfigured_are_503(http, velaris, monkeypatch):
    velaris.down = True
    r = await http.post("/chat/channels/5/messages", json={"body": "x"})
    assert r.status_code == 503 and "refused" not in r.text
    got = [e for e in await chain.read_entries(limit=1000) if e["action"] == "velaris.chat.message.post"]
    assert got[-1]["payload"]["outcome"] == "unavailable"
    assert (await http.get("/mail/mailboxes")).status_code == 503
    monkeypatch.delenv("VELARIS_API_URL")
    monkeypatch.setattr(velaris_proxy, "_client", VelarisClient.from_env)
    assert (await http.get("/control/tasks")).status_code == 503


async def test_velaris_errors_pass_through_without_extras(http, velaris):
    r = await http.get("/chat/channels/9")
    assert r.status_code == 403 and r.json() == {"error": {"code": "forbidden", "message": "no"}}


async def test_size_limits(http, velaris):
    big = b'{"body":"' + b"a" * (64 * 1024) + b'"}'
    r = await http.post("/chat/channels/5/messages", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert (await http.post("/hr/ATS_CORE/pipeline", content=big)).status_code == 413
    assert (await http.post("/chat/files?name=a.bin", content=b"x" * (10 * 1024 * 1024 + 1))).status_code == 413
    assert (await http.post("/chat/channels/5/messages", content=b"not json")).status_code == 400
    assert (await http.post("/chat/channels/5/messages", content=b"5")).status_code == 400
    assert velaris.seen == []


async def test_upload_and_download_use_raw_bodies(http, velaris):
    r = await http.post("/chat/files?name=a.pdf&content_type=application/pdf", content=b"\x00\x01raw",
                        headers={"content-type": "application/pdf"})
    assert r.status_code == 201 and r.json()["size"] == 5
    up = velaris.seen[-1]
    assert up["raw"] == "/chat/files?name=a.pdf&content_type=application%2Fpdf" and up["body"] == b"\x00\x01raw"
    assert up["headers"]["content-type"] == "application/pdf"
    d = await http.get("/chat/files/abc")
    assert d.content == b"PDFBYTES" and d.headers["content-type"] == "application/pdf"
    assert d.headers["x-content-type-options"] == "nosniff" and "set-cookie" not in d.headers
    assert "velaris.chat.file.upload" in await actions()


async def test_ledger_has_no_message_text_and_skips_chatty_calls(http, velaris):
    await http.post("/chat/channels/5/messages", json={"body": "my private words", "local_id": "L1"})
    await http.post("/chat/register")
    await http.get("/chat/channels/5/messages")
    await http.post("/chat/channels/5/read", json={})
    acts = await actions()
    assert acts.count("velaris.chat.message.post") == 2
    assert "velaris.chat.register" not in acts and "velaris.chat.messages" not in acts
    assert "my private words" not in json.dumps(await chain.read_entries(limit=1000))


async def test_long_poll_timeout_is_clamped_and_query_is_signed(http, velaris):
    r = await http.get("/chat/events?queue_id=q1&last_event_id=3&timeout=9999")
    assert r.status_code == 200
    assert velaris.seen[-1]["raw"] == "/chat/events?queue_id=q1&last_event_id=3&timeout=25.0"
    assert (await http.get("/chat/events?timeout=abc")).status_code == 400


async def test_sse_is_passed_through(http, velaris):
    r = await http.get("/chat/events/stream?queue_id=q1&duration=9999")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.content == SSE and "duration=300.0" in velaris.seen[-1]["raw"]
    bad = await http.get("/chat/events/stream?queue_id=bad")
    assert bad.status_code == 410 and bad.json()["error"]["code"] == "bad_queue"


async def test_path_parameters_are_validated_and_emoji_works(http, velaris):
    assert (await http.get("/chat/channels/..%2Fadmin")).status_code in (400, 404)
    assert (await http.get("/mail/mailboxes/a..b/folders")).status_code == 400
    n = len(velaris.seen)
    r = await http.put("/chat/messages/7/reactions/%F0%9F%91%8D")
    assert r.status_code == 200 and len(velaris.seen) == n + 1
    assert velaris.seen[-1]["raw"] == "/chat/messages/7/reactions/%F0%9F%91%8D"


@pytest.mark.asyncio
@pytest.mark.parametrize("ctype", ["text/html", "image/svg+xml", "application/xhtml+xml", "text/xml; charset=utf-8", "text/plain"])
async def test_downloads_are_forced_to_a_safe_download_whatever_velaris_says(ctype):
    from gateway.velaris_proxy import _safe_download_headers
    h = _safe_download_headers({"content-type": ctype, "content-disposition": "inline",
                                "x-content-type-options": "", "content-security-policy": "default-src *"})
    assert h["content-type"] == "application/octet-stream"
    assert h["content-disposition"] == "attachment" and h["x-content-type-options"] == "nosniff"
    assert h["content-security-policy"] == "sandbox; default-src 'none'"
    pdf = _safe_download_headers({"content-type": "application/pdf", "content-disposition": "attachment; filename=a.pdf"})
    assert pdf["content-type"] == "application/pdf" and pdf["content-disposition"].startswith("attachment; filename")


async def test_mail_rule_without_condition_or_value_is_refused(http, velaris):
    """KAN-154: an empty value / no conditions matches every message; refused before Velaris sees it."""
    good = {"name": "n", "enabled": True, "actions": [{"type": "flag"}],
            "conditions": [{"field": "from", "op": "contains", "value": "boss"}]}
    bad = [{**good, "conditions": []},
           {**good, "conditions": [{"field": "from", "op": "contains", "value": " "}]},
           {**good, "conditions": [{"op": "contains", "value": "x"}]}]
    n = len(velaris.seen)
    for body in bad:
        for path in ("/mail/mailboxes/m1/rules", "/mail/mailboxes/m1/rules/dry-run"):
            assert (await http.post(path, json=body)).status_code == 422
    assert (await http.put("/mail/mailboxes/m1/rules/r1", json={**good, "conditions": []})).status_code == 422
    assert len(velaris.seen) == n
    # exists/absent need no value, a disabled rule may keep its old conditions
    ok = {**good, "conditions": [{"field": "list_id", "op": "exists"}]}
    assert (await http.post("/mail/mailboxes/m1/rules", json=ok)).status_code == 200
    assert (await http.put("/mail/mailboxes/m1/rules/r1", json={**good, "enabled": False, "conditions": []})).status_code == 200


async def test_provider_proxy_forwards_with_the_users_roles_and_never_ledgers_a_key(http, velaris):
    key = "sk-live-ABCDEFGH-1234567890"
    r = await http.post("/model-providers", json={"id": "gw", "kind": "openai_compatible", "api_key": key,
                                                  "base_url": "https://gw.example.com/v1"})
    assert r.status_code == 200
    seen = velaris.seen[-1]
    assert (seen["method"], seen["raw"]) == ("POST", "/providers") and json.loads(seen["body"])["api_key"] == key
    assert "model_admin" in seen["claims"]["roles"]                       # owner holds it
    assert (await http.get("/model-providers/usage?days=3")).status_code == 200 and velaris.seen[-1]["raw"] == "/providers/usage?days=3"
    assert (await http.put("/model-providers/gw", json={"enabled": False})).status_code == 200
    assert (await http.delete("/model-providers/gw")).status_code == 200
    assert (await http.post("/model-providers/gw/rotate", json={"api_key": "sk-second-KEY-0000-9999"})).status_code == 200
    entries = [e for e in await chain.read_entries(limit=1000) if e["action"].startswith("velaris.providers.")]
    assert {e["action"] for e in entries} == {"velaris.providers.create", "velaris.providers.update",
                                              "velaris.providers.delete", "velaris.providers.rotate"}
    assert key not in json.dumps(entries) and "sk-second" not in json.dumps(entries)
    assert "api_key" in json.dumps(entries)                                # the field NAME is recorded


async def test_a_member_has_no_provider_role_and_a_viewer_cannot_act(http, velaris):
    http.who["user"] = MEMBER
    assert (await http.get("/model-providers")).status_code == 200        # reaches Velaris, which refuses without the role
    assert "model_admin" not in velaris.seen[-1]["claims"]["roles"]
    async with db.get_session_factory()() as s:
        await s.execute(update(User).where(User.id == DAVE).values(role="viewer"))
        await s.commit()
    n = len(velaris.seen)
    assert (await http.post("/model-providers", json={"id": "x", "kind": "ollama"})).status_code == 403
    assert len(velaris.seen) == n


async def test_dot_segment_and_identity_query_names_are_refused(http, velaris):
    # KAN-69 VP-6 and VP-5
    assert (await http.get("/chat/files/%2e")).status_code == 400
    assert (await http.get("/chat/files/abc?org=other")).status_code == 400
    assert (await http.get("/chat/files/abc?as_user=u2")).status_code == 400
    assert velaris.seen == []
