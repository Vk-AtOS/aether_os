"""One trace id per request, from the browser through the gateway to every log line, Velaris call and ledger entry (KAN-50).

The id is accepted from `X-Trace-Id` (or `X-Request-ID`) only when it looks like an id (8-64 of [A-Za-z0-9._-]); anything
else is replaced, so a caller cannot put newlines or markup into the logs. Tasks created while handling the request copy the
context, so work started by a request keeps its id.
"""
from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from typing import Optional

TRACE_HEADER = "X-Trace-Id"
_VALID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_current: ContextVar[Optional[str]] = ContextVar("aether_trace_id", default=None)


def valid_trace_id(value: Optional[str]) -> bool:
    return bool(value) and _VALID.match(value) is not None


def new_trace_id() -> str:
    return uuid.uuid4().hex


def current_trace_id() -> Optional[str]:
    return _current.get()


def bind_trace_id(trace_id: str):
    """Make `trace_id` current; returns the token for `reset_trace_id`."""
    return _current.set(trace_id)


def reset_trace_id(token) -> None:
    _current.reset(token)


class TraceIdMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so the id is bound for the whole request including streaming responses."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        incoming = {k.lower(): v for k, v in scope.get("headers", [])}
        wanted = (incoming.get(b"x-trace-id") or incoming.get(b"x-request-id") or b"").decode("latin-1")
        trace_id = wanted if valid_trace_id(wanted) else new_trace_id()
        token = bind_trace_id(trace_id)

        async def send_with_id(message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [(k, v) for k, v in message["headers"] if k.lower() != b"x-trace-id"]
                message["headers"].append((b"x-trace-id", trace_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            reset_trace_id(token)
