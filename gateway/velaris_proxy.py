"""Shared engine of the Velaris chat / mail / control / HR proxies (gateway/routers/velaris_*_router.py).

Same rules as velaris_router.py: a signed-in person only (never an API key), the identity comes from
the user's database row and never from headers or the body, the signed request is built by
core/velaris/client.py, Velaris down = 503, Velaris errors pass through as {"error": {code, message}}
and nothing else from their body. Differences, all deliberate:

  * Routes are a TABLE (`Route`), not a pass-through: a method and path that is not in the table does
    not exist here. The HR proxy has its own agent+method table.
  * JSON bodies are capped at 64 KiB like Velaris; raw uploads at 10 MiB (Velaris's chat default; Velaris
    enforces its own, configured, cap too). The body is checked before it is read in full.
  * Ledger: every state-changing call is written to the ledger BEFORE it is made (no entry, no call) and its
    outcome after. Reads, long polls, drafts, read-markers, reactions, pins and flag changes are not
    ledgered (they would drown the chain); exports are. Only ids and field NAMES go in, never message text,
    mail bodies or form values.
  * Long poll and SSE are passed through with a clamped timeout; closing the browser connection drops the
    upstream one.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from aether_os.core.audit import chain as audit_chain
from aether_os.core.velaris.client import Identity, VelarisClient, VelarisUnavailable
from aether_os.core.velaris.identity import identity_for_user
from aether_os.core.velaris.roles import MAY_ACT
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)

MAX_JSON = 64 * 1024
MAX_FILE = 10 * 1024 * 1024
POLL_MAX_S = 25.0
SSE_MAX_S = 300.0
CALL_TIMEOUT_S = 70.0           # Velaris gives a call up to 60 s
_PARAM = re.compile(r"[A-Za-z0-9_.:@-]{1,128}\Z")
_EMOJI = re.compile(r"[^/?#%\\\s]{1,32}\Z")
_PASS_HEADERS = ("content-type", "content-disposition", "x-content-type-options", "cache-control",
                 "content-security-policy", "x-declared-content-type")


_ACTIVE_TYPES = ("text/html", "application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml",
                 "text/javascript", "application/javascript")


def _safe_download_headers(upstream: Any) -> dict:
    """Uploaded bytes are untrusted and are served from the dashboard's own origin: whatever Velaris says, force a
    download, forbid sniffing, sandbox any rendering, and never hand a browser an active content type."""
    h = {k: upstream[k] for k in _PASS_HEADERS if k in upstream}
    ctype = h.get("content-type", "application/octet-stream").split(";")[0].strip().lower()
    if ctype in _ACTIVE_TYPES or ctype.endswith("+xml") or ctype.startswith("text/"):
        h["content-type"] = "application/octet-stream"
    disp = h.get("content-disposition", "")
    h["content-disposition"] = disp if disp.lower().startswith("attachment") else "attachment"
    h["x-content-type-options"] = "nosniff"
    h["content-security-policy"] = "sandbox; default-src 'none'"
    return h


@dataclass(frozen=True)
class Route:
    method: str
    path: str                       # under the prefix; "{name}" segments are validated path parameters
    action: str                     # ledger action: velaris.<action>
    kind: str = "json"              # json | upload | download | poll | sse
    ledger: Optional[bool] = None   # None: ledgered when the method changes state
    log: Tuple[str, ...] = ()       # body fields whose (short) values go in the ledger entry


def _client() -> VelarisClient:
    return VelarisClient.from_env(timeout=CALL_TIMEOUT_S)


def unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Velaris is not available")


async def identity(user: Dict[str, Any], *, acting: bool) -> Identity:
    who = await identity_for_user(user)
    if who is None:
        raise HTTPException(status_code=403, detail="Velaris needs a signed-in person, not an API key")
    if acting and who.org_role not in MAY_ACT:
        raise HTTPException(status_code=403, detail="Your role may look at Velaris but not act in it")
    return who


async def _ledger(who: Identity, action: str, **payload: Any) -> None:
    await audit_chain.append(actor=who.user_id, action=f"velaris.{action}",
                             payload={"org_id": who.org_id, "role": who.org_role, **payload})


async def _ledger_after(who: Identity, action: str, outcome: str, detail: Dict[str, Any]) -> None:
    try:
        await _ledger(who, action, phase="result", outcome=outcome, **detail)
    except Exception as e:  # the call already happened; losing its result entry must be visible
        logger.error("velaris %s: result could not be ledgered: %s", action, e)


def safe_error(status: int, data: Any) -> JSONResponse:
    """Velaris's {"error": {"code", "message"}} and nothing else from its body."""
    err = data.get("error") if isinstance(data, dict) else None
    code = str(err.get("code"))[:60] if isinstance(err, dict) and err.get("code") else "velaris_error"
    msg = str(err.get("message"))[:300] if isinstance(err, dict) and err.get("message") else "Velaris refused the call"
    return JSONResponse({"error": {"code": code, "message": msg}}, status_code=status if status < 500 else 502)


def parse_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        logger.warning("velaris answered HTTP %s without JSON", resp.status_code)
        raise unavailable() from None


def reply(resp: httpx.Response) -> JSONResponse:
    data = parse_json(resp)
    if resp.status_code >= 400:
        return safe_error(resp.status_code, data)
    return JSONResponse(data, status_code=resp.status_code)     # 202 (waiting for approval) passes through


async def read_body(request: Request, limit: int) -> bytes:
    """The request body, refusing before reading everything when it is over `limit`."""
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Content-Length") from None
    if declared > limit:
        raise HTTPException(status_code=413, detail=f"The body may be at most {limit} bytes")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail=f"The body may be at most {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def call(who: Identity, action: str, method: str, path: str, *, body: bytes = b"", query: str = "",
               content_type: Optional[str] = None, timeout: Optional[float] = None, ledger: bool = True,
               detail: Optional[Dict[str, Any]] = None) -> httpx.Response:
    """Ledger, call, ledger the outcome. Raises 503 when Velaris is out."""
    detail = detail or {}
    try:
        client = _client()
    except VelarisUnavailable as e:
        logger.warning("velaris not usable: %s", e)
        raise unavailable() from None
    if ledger:
        await _ledger(who, action, phase="request", **detail)
    try:
        resp = await client.request_raw(who, method, path, body=body, query=query, content_type=content_type,
                                        timeout=timeout)
    except VelarisUnavailable:
        if ledger:
            await _ledger_after(who, action, "unavailable", detail)
        raise unavailable() from None
    if ledger:
        await _ledger_after(who, action, str(resp.status_code), detail)
    return resp


def _check_param(name: str, value: str) -> str:
    ok = bool(_EMOJI.match(value)) if name == "emoji" else bool(_PARAM.match(value))
    if not ok or ".." in value:
        raise HTTPException(status_code=400, detail=f"Invalid {name}")
    return value


_RULE_ACTIONS = ("mail.rule.create", "mail.rule.dry_run", "mail.rule.update")


def check_mail_rule(body: Dict[str, Any]) -> None:
    """A mail rule with no conditions, or a condition with an empty value, matches every message
    (move / mark-read / auto-reply would hit all mail), so an ENABLED one is refused. A disabled
    rule is allowed so an existing match-all rule can still be switched off."""
    if body.get("enabled") is False:
        return
    conds = body.get("conditions")
    if not isinstance(conds, list) or not conds:
        raise HTTPException(status_code=422, detail="A mail rule needs at least one condition (it would match every message)")
    for c in conds:
        if not isinstance(c, dict) or not c.get("field"):
            raise HTTPException(status_code=422, detail="Each rule condition needs a field")
        if c.get("op") not in ("exists", "absent") and not str(c.get("value", "")).strip():
            raise HTTPException(status_code=422, detail="A rule condition needs a value (an empty value matches every message)")


def _query(request: Request, route: Route) -> Tuple[str, float]:
    """The query string to forward (timeouts clamped) and how long the upstream call may take."""
    items = list(request.query_params.multi_items())
    timeout = CALL_TIMEOUT_S
    out = []
    for k, v in items:
        if k == "timeout" and route.kind == "poll":
            try:
                v = str(min(max(float(v), 0.0), POLL_MAX_S))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid timeout") from None
            timeout = float(v) + 10.0
        if k == "duration" and route.kind == "sse":
            try:
                v = str(min(max(float(v), 0.05), SSE_MAX_S))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid duration") from None
            timeout = float(v) + 20.0
        out.append((k, v))
    query = urlencode(out, quote_via=quote)
    if len(query) > 2000:
        raise HTTPException(status_code=414, detail="The query is too long")
    return query, timeout


async def _until_disconnect(request: Request, coro: Any) -> Any:
    """Await `coro`, cancelling it (and so the upstream request) if the browser goes away. None = went away."""
    task = asyncio.ensure_future(coro)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=1.0)
            if done:
                return task.result()
            if await request.is_disconnected():
                return None
    finally:
        if not task.done():
            task.cancel()


def _sse(who: Identity, request: Request, path: str, query: str, timeout: float) -> Any:
    async def start() -> Response:
        try:
            client = _client()
            http, resp = await client.open_stream(who, path, query=query, read_timeout=timeout)
        except VelarisUnavailable as e:
            logger.warning("velaris stream not available: %s", e)
            raise unavailable() from None
        if resp.status_code != 200:             # a bad queue is a JSON error before any stream starts
            body = await resp.aread()
            await resp.aclose()
            await http.aclose()
            try:
                data = json.loads(body)
            except ValueError:
                data = None
            return safe_error(resp.status_code, data)

        async def frames() -> Any:
            try:
                async for chunk in resp.aiter_raw():
                    yield chunk
            except httpx.HTTPError as e:
                logger.info("velaris stream ended: %s", type(e).__name__)
            finally:       # runs on browser disconnect too: the upstream connection is dropped
                await resp.aclose()
                await http.aclose()
        return StreamingResponse(frames(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return start()


def _endpoint(route: Route, upstream: str) -> Any:
    acting = route.method != "GET"
    do_ledger = route.ledger if route.ledger is not None else route.method != "GET"

    async def endpoint(request: Request, user: Dict[str, Any] = Depends(get_current_user)) -> Response:
        who = await identity(user, acting=acting)
        params = {k: _check_param(k, str(v)) for k, v in request.path_params.items()}
        path = upstream + route.path.format(**params)
        query, timeout = _query(request, route)
        body, ctype = b"", None
        detail: Dict[str, Any] = {"params": params}
        if route.kind == "upload":
            body, ctype = await read_body(request, MAX_FILE), request.headers.get("content-type")
            detail["bytes"] = len(body)
        elif route.method in ("POST", "PUT", "PATCH"):
            body = await read_body(request, MAX_JSON)
            if body:
                try:
                    parsed = json.loads(body)
                except ValueError:
                    raise HTTPException(status_code=400, detail="The body is not JSON") from None
                if not isinstance(parsed, (dict, list)):
                    raise HTTPException(status_code=400, detail="The body must be a JSON object")
                if route.action in _RULE_ACTIONS:
                    check_mail_rule(parsed if isinstance(parsed, dict) else {})
                if isinstance(parsed, dict):
                    detail["fields"] = sorted(parsed)[:20]
                    detail.update({k: str(parsed[k])[:80] for k in route.log if k in parsed})
        if route.kind == "sse":
            return await _sse(who, request, path, query, timeout)
        run = call(who, route.action, route.method, path, body=body, query=query, content_type=ctype,
                   timeout=timeout, ledger=do_ledger, detail=detail)
        resp = await _until_disconnect(request, run) if route.kind == "poll" else await run
        if resp is None:
            return JSONResponse({"detail": "client closed the request"}, status_code=499)
        if route.kind == "download" and resp.status_code < 400:
            if len(resp.content) > MAX_FILE:
                return safe_error(502, None)
            return Response(resp.content, status_code=200, headers=_safe_download_headers(resp.headers))
        return reply(resp)

    endpoint.__name__ = f"velaris_{route.action.replace('.', '_')}_{route.method.lower()}"
    return endpoint


def build_router(prefix: str, upstream: str, routes: Tuple[Route, ...], tag: str) -> APIRouter:
    """One authenticated endpoint per table row. Order matters ("/channels/public" before "/channels/{id}")."""
    router = APIRouter(prefix=prefix, tags=[tag])
    for rt in routes:
        router.add_api_route(rt.path, _endpoint(rt, upstream), methods=[rt.method], response_model=None)
    return router
