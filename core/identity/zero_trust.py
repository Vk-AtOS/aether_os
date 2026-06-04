"""
AetherOS Zero-Trust Identity Ticket Issuer

Issues short-lived, signed HMAC-SHA256 tickets that authorise a specific agent
to access a specific resource within a pipeline run.  The ticket is verified
by the receiving component before granting access.

Usage:
    ticket = issue_ticket("/project/run-xyz", "/src/main.py", "python_run")
    verify_ticket(ticket, "/project/run-xyz", "/src/main.py", "python_run")

Environment:
    AETHER_ONE_ZT_SECRET  — shared HMAC secret (required, min 32 bytes)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Optional


_ENV_KEY = "AETHER_ONE_ZT_SECRET"
_TICKET_TTL = 300  # seconds


def _secret() -> bytes:
    val = os.environ.get(_ENV_KEY, "")
    if not val:
        raise RuntimeError(
            f"{_ENV_KEY} must be set before issuing zero-trust tickets. "
            f"Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return val.encode()


def issue_ticket(project_path: str, resource_path: str, action: str) -> str:
    """Return a signed ticket granting *action* on *resource_path* in *project_path*.

    The ticket is a JSON dict with an HMAC-SHA256 signature and an expiry.
    Pass the returned string to verify_ticket() on the receiving side.
    """
    payload = {
        "project": project_path,
        "resource": resource_path,
        "action": action,
        "exp": int(time.time()) + _TICKET_TTL,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    ticket = json.dumps({"body": body, "sig": sig}, separators=(",", ":"))
    return ticket


def verify_ticket(
    ticket: str,
    project_path: str,
    resource_path: str,
    action: str,
) -> bool:
    """Return True iff the ticket is valid, unexpired, and authorises the requested action.

    Raises ValueError with a descriptive message on any verification failure.
    """
    try:
        envelope = json.loads(ticket)
        body_str: str = envelope["body"]
        sig: str = envelope["sig"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise ValueError(f"Malformed ticket: {exc}") from exc

    expected = hmac.new(_secret(), body_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise ValueError("Ticket signature verification failed")

    payload = json.loads(body_str)

    if int(time.time()) > payload.get("exp", 0):
        raise ValueError("Ticket has expired")

    if payload.get("project") != project_path:
        raise ValueError(f"Ticket project mismatch: {payload.get('project')!r} != {project_path!r}")
    if payload.get("resource") != resource_path:
        raise ValueError(f"Ticket resource mismatch: {payload.get('resource')!r} != {resource_path!r}")
    if payload.get("action") != action:
        raise ValueError(f"Ticket action mismatch: {payload.get('action')!r} != {action!r}")

    return True
