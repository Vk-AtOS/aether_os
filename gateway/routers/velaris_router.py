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
from aether_os.core.velaris.roles import MAY_ACT
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.routers.velaris_hr_router import HR_ALLOW

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
    """HR agents are served by /hr with a fixed method list that leaves out erasure and bulk export on
    purpose. This generic route must not reopen them, so an HR agent is reachable here only for the
    methods /hr itself allows (KAN-199)."""
    allowed = HR_ALLOW.get(agent)
    return allowed is not None and method not in allowed


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
    tools = body.get("tools")
    # A flow may hand the model any allowlisted tool, so the same exclusion applies to its tool list.
    if isinstance(tools, list):
        blocked = sorted(t for t in tools if isinstance(t, str) and "." in t and _served_elsewhere(*t.split(".", 1)))
        if blocked:
            raise HTTPException(status_code=400, detail=f"These tools are not available here: {', '.join(blocked[:10])}")
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
