"""Velaris proxy — the dashboard's way to the Velaris HTTP API.

Every endpoint needs a signed-in person (not an API key). Who the call is for comes from the
token's user id and that user's database row, never from headers or the body. Each call is
written to the ledger before it is made (no ledger entry, no call) and its outcome after.
Velaris down or unconfigured = 503. Velaris errors pass through as {"error": {code, message}}
without any exception text; Velaris messages are written there, not taken from exceptions.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from aether_os.core.audit import chain as audit_chain
from aether_os.core.velaris.client import Identity, VelarisClient, VelarisUnavailable
from aether_os.core.velaris.identity import identity_for_user
from aether_os.core.velaris.roles import ADMIN_ROLES, MAY_ACT
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.velaris_proxy import guard_args
from aether_os.gateway.velaris_generic_agents import GENERIC_AGENTS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/velaris", tags=["velaris"])

_NAME = re.compile(r"[A-Za-z0-9_]{1,80}\Z")
_RUN_ID = re.compile(r"[A-Za-z0-9]{1,64}\Z")
_STATUSES = ("real", "rule_based", "not_implemented")
_TIMEOUT_S = 70.0   # Velaris gives a call up to 60 s


def _client() -> VelarisClient:
    return VelarisClient.from_env(timeout=_TIMEOUT_S)


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Velaris is not available")


async def _identity(user: Dict[str, Any], *, acting: bool) -> Identity:
    who = await identity_for_user(user)
    if who is None:
        raise HTTPException(status_code=403, detail="Velaris needs a signed-in person, not an API key")
    if acting and who.org_role not in MAY_ACT:
        raise HTTPException(status_code=403, detail="Your role may look at Velaris but not act in it")
    return who


async def _ledger(who: Identity, action: str, **payload: Any) -> None:
    await audit_chain.append(actor=who.user_id, action=action,
                             payload={"org_id": who.org_id, "role": who.org_role, **payload})


def _safe_error(status: int, data: Any) -> JSONResponse:
    """Velaris's {"error": {"code", "message"}} and nothing else from its body."""
    err = data.get("error") if isinstance(data, dict) else None
    code = str(err.get("code"))[:60] if isinstance(err, dict) and err.get("code") else "velaris_error"
    msg = str(err.get("message"))[:300] if isinstance(err, dict) and err.get("message") else "Velaris refused the call"
    return JSONResponse({"error": {"code": code, "message": msg}}, status_code=status)


async def _forward(who: Identity, action: str, method: str, path: str, *, body: Any = None,
                   detail: Optional[Dict[str, Any]] = None) -> tuple[int, Any]:
    """Ledger, call, ledger the outcome. Returns (status, data); raises 503 when Velaris is out."""
    detail = detail or {}
    try:
        client = _client()
    except VelarisUnavailable as e:
        logger.warning("velaris not usable: %s", e)
        raise _unavailable() from None
    await _ledger(who, f"velaris.{action}", phase="request", **detail)
    try:
        status, data = await client.request(who, method, path, json_body=body)
    except VelarisUnavailable:
        await _ledger_after(who, action, "unavailable", detail)
        raise _unavailable() from None
    await _ledger_after(who, action, str(status), detail)
    return status, data


async def _ledger_after(who: Identity, action: str, outcome: str, detail: Dict[str, Any]) -> None:
    try:
        await _ledger(who, f"velaris.{action}", phase="result", outcome=outcome, **detail)
    except Exception as e:  # the call already happened; losing its result entry must be visible
        logger.error("velaris %s: result could not be ledgered: %s", action, e)


def _served_elsewhere(agent: str, method: str) -> bool:
    """The generic route is an ALLOW-list (KAN-69 VP-4): only an agent named in GENERIC_AGENTS passes. Every HR
    agent is served by /hr, and only there (KAN-199: role check, typed confirmation, caps, ledger rules), and a
    new Velaris agent is unreachable here until someone lists it, so a missing table row can never open a door.
    Exact, case-sensitive match: Velaris agent names are upper case."""
    return agent not in GENERIC_AGENTS


def _checked_tools(tools: Any) -> list:
    """A flow may hand the model any tool, so its list is validated here and fails closed: a list of
    "AGENT.method" names that pass the same name rule as the agent route, none of them excluded by /hr.
    Only this canonical list is forwarded."""
    if not isinstance(tools, list) or not tools:
        raise HTTPException(status_code=400, detail="tools must be a non-empty list of AGENT.method names")
    out, blocked = [], []
    for t in tools:
        agent, _, method = t.partition(".") if isinstance(t, str) else ("", "", "")
        if not (_NAME.match(agent) and _NAME.match(method)):
            raise HTTPException(status_code=400, detail="Each tool must be AGENT.method")
        (blocked if _served_elsewhere(agent, method) else out).append(f"{agent}.{method}")
    if blocked:
        raise HTTPException(status_code=400, detail=f"These tools are not available here: {', '.join(sorted(blocked)[:10])}")
    return out


def _reply(status: int, data: Any) -> Any:
    if status >= 400:
        return _safe_error(status if status < 500 else 502, data)
    return JSONResponse(data, status_code=status)


@router.get("/agents")
async def agents(user: Dict[str, Any] = Depends(get_current_user)) -> Any:
    """Velaris's agent catalogue: department, status, summary, methods (with read/act kind)."""
    who = await _identity(user, acting=False)
    return _reply(*await _forward(who, "agents.list", "GET", "/agents"))


@router.get("/inventory")
async def inventory(user: Dict[str, Any] = Depends(get_current_user)) -> Any:
    """Agents per department with an honest status (derived from GET /agents)."""
    who = await _identity(user, acting=False)
    status, data = await _forward(who, "agents.list", "GET", "/agents")
    if status >= 400 or not isinstance(data, dict):
        return _reply(status, data)
    by_dept: Dict[str, Dict[str, list]] = {}
    for a in data.get("agents", []):
        # Velaris says "unknown" for an agent it could not classify; it is counted as not
        # implemented rather than as working.
        s = a.get("status") if a.get("status") in _STATUSES else "not_implemented"
        by_dept.setdefault(str(a.get("department") or "unassigned"), {s_: [] for s_ in _STATUSES})[s].append(str(a.get("name")))
    totals = {s: 0 for s in _STATUSES}
    departments = []
    for name in sorted(by_dept):
        counts = {s: len(by_dept[name][s]) for s in _STATUSES}
        for s, n in counts.items():
            totals[s] += n
        departments.append({"name": name, "counts": counts, "total": sum(counts.values()),
                            "agents": sorted(({"name": n, "status": s} for s in _STATUSES for n in by_dept[name][s]),
                                             key=lambda x: x["name"])})
    return {"departments": departments, "totals": totals, "total": sum(totals.values())}


@router.post("/agents/{agent}/{method}")
async def call_agent(agent: str, method: str, body: Optional[Dict[str, Any]] = Body(default=None),
                     user: Dict[str, Any] = Depends(get_current_user)) -> Any:
    """Run an agent method. Read methods: 200 {result}. Act methods: 202 {run} waiting for approval
    in the Prime inbox. The method must be on Velaris's own allowlist; Velaris enforces it."""
    if not (_NAME.match(agent) and _NAME.match(method)):
        raise HTTPException(status_code=400, detail="Invalid agent or method name")
    if _served_elsewhere(agent, method):
        raise HTTPException(status_code=404, detail="This agent method is not available here")
    who = await _identity(user, acting=True)
    args = body or {}
    guard_args(args)                     # same guard as every dedicated row: no identity override, page size clamped
    status, data = await _forward(who, "agent.call", "POST", f"/agents/{agent}/{method}", body=args,
                                  detail={"agent": agent, "method": method, "params": sorted(args)[:20]})
    return _reply(status, data)


@router.get("/flows/pending")
async def flows_pending(user: Dict[str, Any] = Depends(get_current_user)) -> Any:
    """The caller's flow runs that wait for a decision (moves them on when Prime has decided)."""
    who = await _identity(user, acting=False)
    return _reply(*await _forward(who, "flows.pending", "GET", "/flows/pending"))


@router.post("/flows")
async def start_flow(body: Dict[str, Any] = Body(...), user: Dict[str, Any] = Depends(get_current_user)) -> Any:
    """Start a model-driven run: {"task": str, "tools": ["AGENT.method", ...]}."""
    guard_args(body)
    tools = _checked_tools(body.get("tools"))
    who = await _identity(user, acting=True)
    detail = {"tools": sorted(t for t in tools if isinstance(t, str))[:30] if isinstance(tools, list) else None}
    return _reply(*await _forward(who, "flow.start", "POST", "/flows",
                                  body={"task": body.get("task"), "tools": tools}, detail=detail))


@router.get("/flows/{run_id}")
async def get_flow(run_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Any:
    """One of the caller's runs; Velaris moves it on if it is free to move."""
    if not _RUN_ID.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")
    who = await _identity(user, acting=False)
    return _reply(*await _forward(who, "flow.read", "GET", f"/flows/{run_id}", detail={"run_id": run_id}))


@router.get("/flows/{run_id}/verify")
async def verify_flow(run_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Any:
    """Check the hash chain of one of the caller's runs: {ok} or the first broken index (KAN-134)."""
    if not _RUN_ID.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")
    who = await _identity(user, acting=False)
    return _reply(*await _forward(who, "flow.verify", "GET", f"/flows/{run_id}/verify", detail={"run_id": run_id}))


@router.get("/trace/verify")
async def verify_trace(user: Dict[str, Any] = Depends(get_current_user)) -> Any:
    """The global trace chain (counts only). Owner/admin: it spans the organisation, not one person's runs."""
    who = await _identity(user, acting=False)
    if who.org_role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only an organisation owner or admin can do this")
    return _reply(*await _forward(who, "trace.verify", "GET", "/trace/verify"))


@router.post("/flows/{run_id}/decide")
async def decide_flow(run_id: str, body: Dict[str, Any] = Body(...),
                      user: Dict[str, Any] = Depends(get_current_user)) -> Any:
    """Decide a waiting run in LOCAL mode (no Prime gate); with Prime Velaris answers 409 decided_in_prime and that
    is passed through. Only call_hash, approve and note are forwarded; the four-eyes rule is Velaris's."""
    if not _RUN_ID.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")
    who = await _identity(user, acting=True)
    if who.org_role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only an organisation owner or admin can do this")
    if not isinstance(body.get("call_hash"), str) or not isinstance(body.get("approve"), bool):
        raise HTTPException(status_code=422, detail="call_hash (text) and approve (true or false) are required")
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise HTTPException(status_code=422, detail="note must be text")
    sent = {"call_hash": body["call_hash"][:128], "approve": body["approve"], **({"note": note[:500]} if note else {})}
    return _reply(*await _forward(who, "flow.decide", "POST", f"/flows/{run_id}/decide", body=sent,
                                  detail={"run_id": run_id, "approve": body["approve"], "call_hash": sent["call_hash"]}))
