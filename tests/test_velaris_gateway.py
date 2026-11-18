"""Velaris proxy router, the velaris.flow executor and the Prime service endpoints,
against a fake Velaris (httpx MockTransport) and the real Prime services/ledger."""
# ruff: noqa: F811,F401  (a fixture imported by name and then requested as an argument)
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException
from sqlalchemy import update

import aether_os.core.db as db
from aether_os.core.models import User
from aether_os.core.velaris.client import VelarisClient
from aether_os.core.audit import chain
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers import prime_service_router as service_api
from aether_os.gateway.routers import velaris_router
from aether_os.prime.approvals import RequestError
from aether_os.prime import AutonomyLevel, Delegation, Limits, DelegationRepository, executors
from aether_os.prime.executors import velaris_call_hash
from aether_os.tests.prime_helpers import (  # noqa: F401  (svc is a fixture)
    ALICE, API_KEY, BOB, BOB_IDS, counting, DAVE, MALLORY, ORG, OTHER_ORG, OWNER, MEMBER, OUTSIDER, svc,
)

pytestmark = pytest.mark.asyncio
SECRET = "x" * 40
KEY = Ed25519PrivateKey.generate()
OTHER_KEY = {"sub": "api_key", "org_id": OTHER_ORG, "role": "api"}


class FakeVelaris:
    """Answers like Velaris; remembers what it was sent."""

    def __init__(self):
        self.seen, self.down = [], False
        self.run = {"run_id": "run1", "status": "waiting_approval", "result": "needs approval",
                    "pending": None, "turns": 0}
        self.agents = {"agents": [
            {"name": "PAYROLL_ENGINE", "department": "finance", "status": "real", "summary": "x", "methods": []},
            {"name": "TDS_ENGINE", "department": "finance", "status": "rule_based", "summary": "", "methods": []},
            {"name": "OLD", "department": "hr", "status": "weird", "summary": "", "methods": []},
            {"name": "LOOSE", "department": None, "status": "real", "summary": "", "methods": []}], "failed": []}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused")
        claims = json.loads(base64.urlsafe_b64decode(req.headers["x-velaris-identity"].split(".")[0] + "=="))
        body = json.loads(req.content) if req.content else None
        self.seen.append({"method": req.method, "path": req.url.raw_path.decode(), "claims": claims,
                          "body": body, "headers": dict(req.headers)})
        p = req.url.path
        if p == "/agents" and req.method == "GET":
            return httpx.Response(200, json=self.agents)
        if p == "/agents/LOGISTA/apply":
            return httpx.Response(202, json={"kind": "act", "approval": "prime", "run": self.run})
        if p == "/agents/TACTICIAN/huge":
            return httpx.Response(200, json={"kind": "read", "result": "x" * (5 * 1024 * 1024)})
        if p == "/agents/TACTICIAN/get":
            return httpx.Response(200, json={"kind": "read", "result": {"ok": True}})
        if p == "/agents/TACTICIAN/secret":
            return httpx.Response(403, json={"error": {"code": "access_denied", "message": "no",
                                                       "trace": "Traceback (most recent call last)"}})
        if p == "/flows/pending":
            return httpx.Response(200, json={"runs": [], "approval": "prime"})
        if p == "/flows/run1":
            return httpx.Response(200, json=self.run)
        if p == "/flows/other":
            return httpx.Response(404, json={"error": {"code": "unknown_run", "message": "no such run"}})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "no such endpoint"}})


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
    monkeypatch.setattr(velaris_router, "_client",
                        lambda: VelarisClient.from_env(transport=transport))
    monkeypatch.setattr(executors, "velaris_transport", transport)
    return fake


@pytest.fixture
def http(svc, velaris):
    who = {"user": OWNER}
    app = FastAPI()
    app.include_router(velaris_router.router)
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    client.who = who
    return client


async def ledger_actions():
    return [e["action"] for e in await chain.read_entries(limit=1000)]


# ── proxy ─────────────────────────────────────────────────────────────────────

async def test_inventory_keeps_the_old_shape(http, velaris):
    r = await http.get("/velaris/inventory")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 4 and d["totals"] == {"real": 2, "rule_based": 1, "not_implemented": 1}
    fin = next(x for x in d["departments"] if x["name"] == "finance")
    assert fin["counts"] == {"real": 1, "rule_based": 1, "not_implemented": 0} and fin["total"] == 2
    assert {"name": "PAYROLL_ENGINE", "status": "real"} in fin["agents"]
    assert {x["name"] for x in d["departments"]} == {"finance", "hr", "unassigned"}
    assert "velaris.agents.list" in await ledger_actions()


async def test_agents_lists_the_catalogue(http, velaris):
    assert (await http.get("/velaris/agents")).json()["agents"][0]["name"] == "PAYROLL_ENGINE"


async def test_read_call_is_200_and_identity_comes_from_the_database(http, velaris):
    # Alice is an owner in the database; nothing the request says can change that.
    r = await http.post("/velaris/agents/TACTICIAN/get", json={"employee_id": "e1", "roles": ["x"]},
                        headers={"X-Caller-Roles": "hr_admin", "X-Velaris-Identity": "forged",
                                 "X-Caller-Id": "root"})
    assert r.status_code == 200 and r.json()["result"] == {"ok": True}
    seen = velaris.seen[-1]
    assert seen["claims"]["sub"] == ALICE and seen["claims"]["org"] == ORG
    assert "governance_admin" in seen["claims"]["roles"]
    assert seen["headers"]["x-velaris-identity"] != "forged" and "x-caller-id" not in seen["headers"]
    assert seen["body"] == {"employee_id": "e1", "roles": ["x"]}      # arguments only; never identity


async def test_role_comes_from_the_row_not_the_token(http, velaris):
    async with db.get_session_factory()() as s:
        await s.execute(update(User).where(User.id == DAVE).values(role="viewer"))
        await s.commit()
    http.who["user"] = {**MEMBER, "role": "owner"}          # a stale/forged token claim
    assert (await http.post("/velaris/agents/TACTICIAN/get", json={})).status_code == 403  # viewer cannot act
    assert (await http.get("/velaris/agents")).status_code == 200                    # but may look
    assert velaris.seen[-1]["claims"]["roles"] == []


async def test_act_call_is_202_pending_approval(http, velaris):
    r = await http.post("/velaris/agents/LOGISTA/apply", json={"days": 2})
    assert r.status_code == 202 and r.json()["run"]["status"] == "waiting_approval"


async def test_velaris_error_passes_through_without_extras(http, velaris):
    r = await http.post("/velaris/agents/TACTICIAN/secret", json={})
    assert r.status_code == 403 and r.json() == {"error": {"code": "access_denied", "message": "no"}}


async def test_velaris_down_is_503_and_ledgered(http, velaris):
    velaris.down = True
    r = await http.get("/velaris/inventory")
    assert r.status_code == 503 and "refused" not in r.text
    entries = [e for e in await chain.read_entries(limit=1000) if e["action"] == "velaris.agents.list"]
    assert [e["payload"]["phase"] for e in entries] == ["request", "result"]
    assert entries[-1]["payload"]["outcome"] == "unavailable"


async def test_unconfigured_is_503(http, velaris, monkeypatch):
    monkeypatch.delenv("VELARIS_API_URL")
    monkeypatch.setattr(velaris_router, "_client", VelarisClient.from_env)
    assert (await http.get("/velaris/agents")).status_code == 503


async def test_api_keys_and_strangers_are_refused(http, velaris):
    for path in ("/velaris/agents", "/velaris/inventory", "/velaris/flows/pending", "/velaris/flows/run1"):
        http.who["user"] = API_KEY
        assert (await http.get(path)).status_code == 403
        http.who["user"] = {"user_id": "ghost", "org_id": ORG, "role": "owner"}
        assert (await http.get(path)).status_code == 403
        http.who["user"] = {**OUTSIDER, "org_id": ORG}          # right id, wrong organisation
        assert (await http.get(path)).status_code == 403
    assert velaris.seen == []


async def test_endpoints_need_a_token():
    app = FastAPI()
    app.include_router(velaris_router.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        for method, path in (("GET", "/velaris/agents"), ("GET", "/velaris/inventory"),
                             ("POST", "/velaris/agents/TACTICIAN/b"), ("GET", "/velaris/flows/pending"),
                             ("POST", "/velaris/flows"), ("GET", "/velaris/flows/r1")):
            assert (await c.request(method, path)).status_code == 401, path


async def test_names_are_validated(http, velaris):
    assert (await http.post("/velaris/agents/A..B/x", json={})).status_code in (400, 404)
    assert (await http.post("/velaris/agents/A/b%3Fx", json={})).status_code == 400
    assert (await http.get("/velaris/flows/a-b")).status_code == 400
    assert velaris.seen == []


async def test_generic_route_cannot_reopen_what_the_hr_proxy_leaves_out(http, velaris):
    # KAN-199: erasure and bulk export of employee and candidate data are deliberately not on /hr;
    # the generic route and flow tools must not reach them either, and Velaris is never called.
    for agent, method in (("EMPLOYEE_RECORDS", "erase_subject"), ("EMPLOYEE_RECORDS", "export_subject"),
                          ("ATS_CORE", "erase_candidates"), ("ATS_CORE", "export_candidate")):
        assert (await http.post(f"/velaris/agents/{agent}/{method}", json={})).status_code == 404
    r = await http.post("/velaris/flows", json={"task": "t", "tools": ["TACTICIAN.get", "EMPLOYEE_RECORDS.erase_subject"]})
    assert r.status_code == 400 and "EMPLOYEE_RECORDS.erase_subject" in r.json()["detail"]
    assert (await http.post("/velaris/agents/employee_records/erase_subject", json={})).status_code == 404
    # the flow tool list fails closed: anything that is not a list of AGENT.method names is refused
    for bad in (None, "EMPLOYEE_RECORDS.erase_subject", [], [1], ["NODOT"], ["A.b c"], ["A..b"],
                ["employee_records.erase_subject"], {"t": "A.b"}):
        assert (await http.post("/velaris/flows", json={"task": "t", "tools": bad})).status_code == 400, bad
    assert velaris.seen == []
    # every HR agent is /hr-only, even for methods /hr allows; an agent /hr does not serve still passes through
    assert (await http.post("/velaris/agents/EMPLOYEE_RECORDS/get_employee", json={})).status_code == 404
    assert (await http.post("/velaris/agents/TACTICIAN/get", json={})).status_code == 200
    assert [s["path"] for s in velaris.seen] == ["/agents/TACTICIAN/get"]


async def test_flows(http, velaris):
    assert (await http.get("/velaris/flows/pending")).json()["approval"] == "prime"
    assert (await http.get("/velaris/flows/run1")).json()["run_id"] == "run1"
    assert (await http.get("/velaris/flows/other")).status_code == 404
    r = await http.post("/velaris/flows", json={"task": "t", "tools": ["TACTICIAN.b"]})
    assert r.status_code == 404      # the fake knows no POST /flows; the call was forwarded signed
    assert velaris.seen[-1]["body"] == {"task": "t", "tools": ["TACTICIAN.b"]}


# ── executor ──────────────────────────────────────────────────────────────────

TOOL, ARGS = "LEAVE_MANAGEMENT.apply", {"employee_id": "e1", "days": 2}


def flow_params(**kw):
    return {"run_id": "run1", "tool": TOOL, "args": ARGS, "reason": "needs approval",
            "call_hash": velaris_call_hash(TOOL, ARGS), **kw}


async def submit_flow(svc, params=None, scope="velaris.flow.call"):
    from aether_os.prime import Action
    now = datetime.now(timezone.utc)
    await DelegationRepository().add(Delegation(
        grantor=ALICE, deputy="bob@a.test", autonomy=AutonomyLevel.ACT_WITH_APPROVAL, scope={scope},
        valid_from=now - timedelta(hours=1), valid_until=now + timedelta(days=2)), org_id=ORG)
    out = await svc.submit(Action(type="velaris.flow.call", on_behalf_of=ALICE, requested_by="system:api_key",
                                  params=params or flow_params()), ORG, "velaris.flow")
    return out["request"]


async def approve(svc, req):
    return await svc.decide(req["id"], BOB, BOB_IDS, ORG, req["request_hash"], approve=True)


async def test_describe_is_readable_and_bound_to_the_hash(svc, velaris):
    req = await submit_flow(svc)
    assert req["what_will_happen"].startswith(f"Run {TOOL} with ")
    assert '"days": 2' in req["what_will_happen"] and f"on behalf of {ALICE}" in req["what_will_happen"]
    assert req["action"]["params"]["call_hash"] == velaris_call_hash(TOOL, ARGS)
    # the hash the approver quotes covers the params, including the call hash
    assert len(req["request_hash"]) == 64


async def test_executor_needs_a_second_person(svc, velaris):
    req = await submit_flow(svc)
    assert req["state"] == "pending"            # requested by the system for Alice: waits for Bob
    from aether_os.prime.executors import REGISTRY
    assert "velaris.flow" in __import__("aether_os.prime.authz", fromlist=["x"]).EXTERNAL_EFFECT
    assert REGISTRY["velaris.flow"].name == "velaris.flow"


async def test_approved_and_run_waits_on_the_same_call_succeeds_signed_as_the_person(svc, velaris):
    velaris.run["pending"] = {"tool": TOOL, "args": ARGS, "reason": "x", "call_hash": velaris_call_hash(TOOL, ARGS)}
    res = await approve(svc, await submit_flow(svc))
    assert res["execution"]["status"] == "succeeded" and res["execution"]["result"]["advanced"] is False
    seen = velaris.seen[-1]
    assert (seen["method"], seen["path"]) == ("GET", "/flows/run1")
    assert seen["claims"]["sub"] == ALICE        # the person the run is for, not the approver


async def test_run_that_moved_on_reports_advanced(svc, velaris):
    velaris.run["status"] = "done"
    res = await approve(svc, await submit_flow(svc))
    assert res["execution"]["status"] == "succeeded" and res["execution"]["result"] == {
        "run_id": "run1", "run_status": "done", "advanced": True}


async def test_run_waiting_on_another_call_fails(svc, velaris):
    velaris.run["pending"] = {"call_hash": "0" * 64}
    res = await approve(svc, await submit_flow(svc))
    assert res["execution"]["status"] == "failed"
    assert "different call" in res["execution"]["result"]["error"]


async def test_unknown_run_fails(svc, velaris):
    req = await submit_flow(svc, flow_params(run_id="other"))
    assert (await approve(svc, req))["execution"]["status"] == "failed"


async def test_velaris_down_needs_attention_not_failed(svc, velaris):
    velaris.down = True
    res = await approve(svc, await submit_flow(svc))
    assert res["execution"]["status"] == "needs_attention"


async def test_call_hash_that_does_not_match_the_arguments_never_runs(svc, velaris):
    req = await submit_flow(svc, flow_params(call_hash="a" * 64))
    assert req["what_will_happen"].startswith("Would fail:")
    assert (await approve(svc, req))["execution"]["status"] == "failed"
    assert velaris.seen == []


async def test_person_who_left_the_organisation_fails(svc, velaris):
    req = await submit_flow(svc)
    async with db.get_session_factory()() as s:
        await s.execute(update(User).where(User.id == ALICE).values(is_active=False))
        await s.commit()
    with pytest.raises(RequestError):       # Prime itself refuses: the person no longer holds authority
        await approve(svc, req)
    assert velaris.seen == []


# ── Prime service endpoints ──────────────────────────────────────────────────

async def test_service_request_view(svc, velaris):
    req = await submit_flow(svc)
    view = await service_api.service_request(req["id"], user=API_KEY)
    assert view["request_hash"] == req["request_hash"] and view["state"] == "pending"
    assert view["action"]["params"]["run_id"] == "run1"
    res = await approve(svc, req)
    view = await service_api.service_request(req["id"], user=API_KEY)
    assert view["state"] == "approved" and view["decided_by"] == BOB
    assert view["execution"]["status"] == res["execution"]["status"]


async def test_service_request_is_org_bound_and_key_only(svc, velaris):
    req = await submit_flow(svc)
    with pytest.raises(HTTPException) as e:
        await service_api.service_request(req["id"], user=OTHER_KEY)
    assert e.value.status_code == 404
    for person in (OWNER, MEMBER, OUTSIDER):
        with pytest.raises(HTTPException) as e:
            await service_api.service_request(req["id"], user=person)
        assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await service_api.service_request("nope", user=API_KEY)
    assert e.value.status_code == 404


async def test_service_request_only_shows_velaris_requests(svc, velaris, counting):
    from aether_os.tests.prime_helpers import act, grant
    await grant()
    other = (await svc.submit(act(), ORG, "counting"))["request"]
    with pytest.raises(HTTPException) as e:
        await service_api.service_request(other["id"], user=API_KEY)
    assert e.value.status_code == 404


def read(caller, category="pay", subject="e1", org=ORG, roles=()):
    return service_api.ReadIn(caller={"id": caller, "org": ORG, "roles": list(roles)},
                              category=category, subject_id=subject, org=org)


async def test_authorize_read_uses_the_stored_role_and_denies_by_default(svc, velaris):
    ok = await service_api.authorize_read(read(ALICE), user=API_KEY)            # owner -> hr/payroll
    assert ok["allowed"] is True and ok["reason"].startswith("role ")
    # a member who claims hr_admin gets nothing: Velaris's claim is not used
    assert (await service_api.authorize_read(read(DAVE, roles=["hr_admin"]), user=API_KEY))["allowed"] is False
    assert (await service_api.authorize_read(read(ALICE, category="nope"), user=API_KEY))["allowed"] is False
    assert (await service_api.authorize_read(read(ALICE, org=OTHER_ORG), user=API_KEY))["allowed"] is False
    assert (await service_api.authorize_read(read("ghost"), user=API_KEY))["allowed"] is False
    other = service_api.ReadIn(caller={"id": ALICE, "org": OTHER_ORG}, category="pay")
    assert (await service_api.authorize_read(other, user=API_KEY))["allowed"] is False
    assert (await service_api.authorize_read(read(MALLORY), user=API_KEY))["allowed"] is False  # other org's person
    entries = [e for e in await chain.read_entries(limit=1000) if e["action"] == "prime.service.authorize_read"]
    assert len(entries) == 7 and entries[0]["payload"]["allowed"] is True


async def test_authorize_read_refuses_people_and_other_keys_cannot_widen(svc, velaris):
    with pytest.raises(HTTPException) as e:
        await service_api.authorize_read(read(ALICE), user=OWNER)
    assert e.value.status_code == 403
    # another organisation's key cannot ask about this organisation's person
    assert (await service_api.authorize_read(read(ALICE), user=OTHER_KEY))["allowed"] is False


async def test_authorize_read_fails_closed_when_the_ledger_is_down(svc, velaris, monkeypatch):
    async def broken(*a, **k):
        raise RuntimeError("ledger down")
    monkeypatch.setattr(service_api.audit_chain, "append", broken)
    with pytest.raises(HTTPException) as e:
        await service_api.authorize_read(read(ALICE), user=API_KEY)
    assert e.value.status_code == 503


async def test_generic_route_is_an_allow_list(http, velaris):
    # KAN-69 VP-4: an agent that nobody listed (a new HR agent missing from the table, a typo) is not reachable
    assert (await http.post("/velaris/agents/BRAND_NEW_AGENT/read_all", json={})).status_code == 404
    r = await http.post("/velaris/flows", json={"task": "t", "tools": ["BRAND_NEW_AGENT.read_all"]})
    assert r.status_code == 400
    assert velaris.seen == []


async def test_generic_route_refuses_an_oversized_answer(http, velaris):
    # KAN-69 VP-7: the table proxies cap the answer at 4 MiB; the generic agent route had no cap
    assert (await http.post("/velaris/agents/TACTICIAN/huge", json={})).status_code == 503
