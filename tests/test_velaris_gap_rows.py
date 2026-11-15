"""KAN-129..151 gateway rows: one table-driven check per rule, over every row of the shared proxy definition.

Fake Velaris = httpx MockTransport. Rules proven: role (member refused before Velaris is called), typed
confirmation, identity-override refusal (org scoping), page-size clamp, per-row timeout, answer cap, ledger holds
names only, export is a safe download, and the generic route never reaches a dedicated-only row (KAN-199).
"""
# ruff: noqa: F811,F401  (fixtures imported by name)
from __future__ import annotations

import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI

from aether_os.core.audit import chain
from aether_os.core.velaris.client import VelarisClient
from aether_os.gateway import velaris_proxy
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers import (velaris_chat_router, velaris_control_router, velaris_hr_router,
                                       velaris_mail_router, velaris_router)
from aether_os.gateway.velaris_hr_table import HR_DEDICATED, HR_ROUTES
from aether_os.tests.prime_helpers import ADMIN, DAVE, MEMBER, ORG, OWNER, svc  # noqa: F401
from aether_os.tests.test_velaris_proxies import KEY, SECRET

pytestmark = pytest.mark.asyncio
ROUTERS = (velaris_chat_router, velaris_mail_router, velaris_control_router, velaris_hr_router, velaris_router)
TABLE_ROWS = [r for m in (velaris_chat_router, velaris_mail_router) for r in m.ROUTES if r.admin or r.confirm] + [
    r for r in HR_ROUTES if r.admin or r.confirm]


class Fake:
    def __init__(self):
        self.seen, self.reply = [], None

    def __call__(self, req: httpx.Request) -> httpx.Response:
        claims = json.loads(base64.urlsafe_b64decode(req.headers["x-velaris-identity"].split(".")[0] + "=="))
        self.seen.append({"method": req.method, "raw": req.url.raw_path.decode(), "claims": claims,
                          "body": req.content, "timeout": req.extensions.get("timeout")})
        return self.reply(req) if self.reply else httpx.Response(200, json={"result": {"ok": True}})


@pytest.fixture
def velaris(monkeypatch, tmp_path):
    fake = Fake()
    pem = tmp_path / "id.pem"
    pem.write_bytes(KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    monkeypatch.setenv("VELARIS_API_URL", "http://velaris.test")
    monkeypatch.setenv("VELARIS_API_SECRET", SECRET)
    monkeypatch.setenv("VELARIS_IDENTITY_PRIVATE_KEY", str(pem))
    transport = httpx.MockTransport(fake)
    factory = lambda: VelarisClient.from_env(transport=transport)  # noqa: E731
    monkeypatch.setattr(velaris_proxy, "_client", factory)
    monkeypatch.setattr(velaris_router, "_client", factory)
    return fake


@pytest.fixture
def http(svc, velaris):
    who = {"user": OWNER}
    app = FastAPI()
    for m in ROUTERS:
        app.include_router(m.router)
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.who = who
    return c


def url_of(row, prefix):
    return prefix + row.path.replace("{", "").replace("}", "")


def _prefix(row):
    for m, pre in ((velaris_chat_router, "/chat"), (velaris_mail_router, "/mail")):
        if row in m.ROUTES:
            return pre
    return "/hr"


async def test_every_admin_row_refuses_a_member_before_velaris_is_called(http, velaris):
    http.who["user"] = MEMBER
    assert len(TABLE_ROWS) > 60
    for row in TABLE_ROWS:
        r = await http.request(row.method, url_of(row, _prefix(row)), json={"confirm": row.confirm} if row.confirm else {})
        assert r.status_code == 403, (row.method, row.path)
        assert "owner or admin" in r.json()["detail"]
    assert velaris.seen == []


async def test_an_admin_role_reaches_the_rows(http, velaris):
    http.who["user"] = ADMIN
    for row in TABLE_ROWS:
        if row.kind == "sse":
            continue
        body = {"confirm": row.confirm} if row.confirm else {}
        r = await http.request(row.method, url_of(row, _prefix(row)), json=body)
        assert r.status_code == 200, (row.method, row.path, r.text)
    assert len(velaris.seen) == len(TABLE_ROWS)


async def test_typed_confirmation_is_required_and_not_forwarded(http, velaris):
    for path in ("/hr/EMPLOYEE_RECORDS/erase_subject", "/hr/ATS_CORE/erase_candidates", "/chat/admin/users/u1/erase",
                 "/mail/mailboxes/m1"):
        method = "DELETE" if path == "/mail/mailboxes/m1" else "POST"
        for body in (None, {}, {"confirm": "erase"}, {"confirm": "EXPORT"}, {"confirm": True}):
            r = await http.request(method, path, **({"json": body} if body is not None else {}))
            assert r.status_code == 422 and "Type ERASE" in r.json()["detail"], (path, body)
    assert velaris.seen == []
    r = await http.post("/hr/EMPLOYEE_RECORDS/erase_subject", json={"confirm": "ERASE", "employee_id": "e1"})
    assert r.status_code == 200 and json.loads(velaris.seen[-1]["body"]) == {"employee_id": "e1"}
    r = await http.request("DELETE", "/mail/mailboxes/m1", json={"confirm": "ERASE"})
    assert r.status_code == 200 and velaris.seen[-1]["body"] == b"" and velaris.seen[-1]["method"] == "DELETE"


async def test_exports_are_ledgered_safe_downloads(http, velaris):
    velaris.reply = lambda req: httpx.Response(200, json={"result": {"records": [1, 2]}})
    for method, path, body in (("POST", "/hr/EMPLOYEE_RECORDS/export_subject", {"confirm": "EXPORT", "employee_id": "e1"}),
                               ("POST", "/hr/ATS_CORE/export_candidate", {"confirm": "EXPORT", "candidate_id": "c1"}),
                               ("GET", "/chat/admin/users/u1/export", None), ("GET", "/chat/me/export", None),
                               ("POST", "/hr/ESIGN/get_sealed_document", {"request_id": "r1"})):
        r = await http.request(method, path, **({"json": body} if body else {}))
        assert r.status_code == 200, path
        assert r.headers["content-disposition"].startswith("attachment") and r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["content-security-policy"].startswith("sandbox")
        assert r.json()["result"]["records"] == [1, 2]
    acts = [e["action"] for e in await chain.read_entries(limit=1000)]
    assert acts.count("velaris.hr.call") == 3 * 2 and "velaris.chat.me.export" in acts and "velaris.chat.admin.user.export" in acts
    payload = json.dumps(await chain.read_entries(limit=1000))
    assert '"e1"' not in payload and '"c1"' not in payload and "employee_id" in payload   # names, never values


async def test_identity_and_org_cannot_be_overridden_by_the_body(http, velaris):
    for body in ({"org_id": "other"}, {"reviewed_by": "me"}, {"tenant_id": "x"}, {"actor": "boss"}):
        r = await http.post("/hr/LEAVE_MANAGEMENT/apply", json=body)
        assert r.status_code == 400 and "sign-in" in r.json()["detail"]
    assert velaris.seen == []
    assert (await http.post("/hr/LEAVE_MANAGEMENT/apply", json={"from": "2026-01-01"})).status_code == 200
    assert velaris.seen[-1]["claims"]["org"] == ORG and velaris.seen[-1]["claims"]["sub"] == OWNER["user_id"]


async def test_page_size_is_clamped_in_query_and_body(http, velaris):
    await http.get("/chat/channels/5/messages?limit=100000&before=3")
    assert "limit=200" in velaris.seen[-1]["raw"] and "before=3" in velaris.seen[-1]["raw"]
    await http.post("/hr/ATS_CORE/list_requisitions", json={"limit": 999999, "state": "open"})
    assert json.loads(velaris.seen[-1]["body"]) == {"limit": 200, "state": "open"}
    await http.post("/hr/ATS_CORE/list_requisitions", json={"limit": 0})
    assert json.loads(velaris.seen[-1]["body"]) == {"limit": 1}
    n = len(velaris.seen)
    assert (await http.post("/hr/ATS_CORE/list_requisitions", json={"limit": "many"})).status_code == 400
    assert (await http.get("/chat/channels/5/messages?limit=abc")).status_code == 400
    assert len(velaris.seen) == n


async def test_each_row_has_a_timeout_and_slow_ones_get_more(http, velaris):
    assert all(r.timeout for r in HR_ROUTES)
    by = {r.path: r.timeout for r in HR_ROUTES}
    assert by["/PAYROLL_ENGINE/compute_bulk"] > by["/LEAVE_MANAGEMENT/get_balance"]
    await http.post("/hr/LEAVE_MANAGEMENT/get_balance", json={})
    assert velaris.seen[-1]["timeout"]["read"] == 30.0


async def test_an_oversized_answer_is_refused_not_relayed(http, velaris):
    velaris.reply = lambda req: httpx.Response(200, content=b'{"result":"' + b"a" * (4 * 1024 * 1024) + b'"}',
                                               headers={"content-type": "application/json"})
    r = await http.post("/hr/ATS_CORE/list_requisitions", json={})
    assert r.status_code == 502 and r.json()["error"]["code"] == "velaris_error"


async def test_account_secret_and_hr_values_never_reach_the_ledger(http, velaris):
    r = await http.post("/mail/mailboxes/m1/accounts", json={"host": "imap.example.com", "user": "u", "secret": "hunter2-pw"})
    assert r.status_code == 200 and b"hunter2-pw" in velaris.seen[-1]["body"]      # forwarded to Velaris...
    await http.post("/hr/ONBOARDING_FLOW/submit_identifier", json={"kind": "pan", "value": "ABCDE1234F"})
    await http.post("/hr/PAYROLL_ENGINE/compute", json={"month": "2026-04", "employee_id": "emp-77"})
    await http.post("/mail/mailboxes", json={"address": "ceo@example.com"})
    ledger = json.dumps(await chain.read_entries(limit=1000))
    for leaked in ("hunter2-pw", "ABCDE1234F", "emp-77", "ceo@example.com", "imap.example.com"):
        assert leaked not in ledger, leaked                                           # ...never to the ledger
    assert "secret" in ledger                                                          # field NAMES only


async def test_dedicated_only_rows_are_not_reachable_on_the_generic_route_or_as_flow_tools(http, velaris):
    assert len(HR_DEDICATED) > 40
    for agent, method in sorted(HR_DEDICATED):
        assert (await http.post(f"/velaris/agents/{agent}/{method}", json={})).status_code == 404, (agent, method)
        assert (await http.post(f"/velaris/agents/{agent.lower()}/{method}", json={})).status_code == 404
    r = await http.post("/velaris/flows", json={"task": "t", "tools": ["PAYROLL_ENGINE.compute_bulk"]})
    assert r.status_code == 400
    assert velaris.seen == []
    assert (await http.post("/velaris/agents/PAYROLL_ENGINE/get_payslip", json={})).status_code == 200   # member-level row


async def test_flow_verify_trace_and_decide(http, velaris):
    r = await http.get("/velaris/flows/run1/verify")
    assert r.status_code == 200 and velaris.seen[-1]["raw"] == "/flows/run1/verify"
    assert (await http.get("/velaris/flows/a-b/verify")).status_code == 400
    assert (await http.get("/velaris/trace/verify")).status_code == 200
    http.who["user"] = MEMBER
    assert (await http.get("/velaris/trace/verify")).status_code == 403
    assert (await http.post("/velaris/flows/run1/decide", json={"call_hash": "h", "approve": True})).status_code == 403
    assert (await http.get("/velaris/flows/run1/verify")).status_code == 200      # a member verifies their own run
    http.who["user"] = OWNER
    n = len(velaris.seen)
    for bad in ({}, {"call_hash": "h"}, {"call_hash": 1, "approve": True}, {"call_hash": "h", "approve": "yes"}):
        assert (await http.post("/velaris/flows/run1/decide", json=bad)).status_code == 422
    assert (await http.post("/velaris/flows/bad id/decide", json={"call_hash": "h", "approve": True})).status_code in (400, 404)
    assert len(velaris.seen) == n
    velaris.reply = lambda req: httpx.Response(409, json={"error": {"code": "decided_in_prime", "message": "Prime decides"}})
    r = await http.post("/velaris/flows/run1/decide", json={"call_hash": "h", "approve": False, "note": "no", "approve_all": 1, "x": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "decided_in_prime"
    assert json.loads(velaris.seen[-1]["body"]) == {"call_hash": "h", "approve": False, "note": "no"}
    acts = [e["action"] for e in await chain.read_entries(limit=1000)]
    assert acts.count("velaris.flow.decide") == 2 and "velaris.flow.verify" in acts


async def test_velaris_down_is_503_on_new_routes(http, velaris):
    def boom(req):
        raise httpx.ConnectError("refused")
    velaris.reply = boom
    for method, path in (("GET", "/velaris/flows/r1/verify"), ("POST", "/hr/LEAVE_MANAGEMENT/apply"),
                         ("POST", "/mail/mailboxes/m1/sync"), ("GET", "/velaris/trace/verify")):
        assert (await http.request(method, path, json={})).status_code == 503, path
