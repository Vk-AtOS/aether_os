"""
Aether-One Zero-Trust Execution Core

Goal:
    No sensitive action (e.g. running code, applying patches) should happen
    without a signed "ticket" approved by the system.

This module provides:
    - A simple HMAC-based ticket system for offline use.
    - Safe to extend later with hardware keys or org PKI.

Ticket shape (dict):
    {
        "project_path": "...",
        "file_path": "...",
        "action": "python_run" | "python_fix" | "...",
        "issued_at": "<iso8601>",
        "signature": "<hex-hmac>",
    }

Public API:

    issue_ticket(project_path, file_path, action) -> dict
    verify_ticket(ticket: dict) -> dict  # { ok: bool, reason: str | None }

NOTE:
    This is a core primitive. It does NOT enforce anything itself.
    Enforcement is done by callers (API/CLI) that require a valid ticket.
"""

from __future__ import annotations

import json
import os
import hmac
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Tuple


# Env var for secret key (can be rotated by ops)
_ZT_SECRET_ENV = "AETHER_ONE_ZT_SECRET"


def _get_secret() -> bytes:
    """
    Get the HMAC secret from the AETHER_ONE_ZT_SECRET environment variable.

    BUG 2 FIX: Removed hardcoded dev default. The env var MUST be set.
    Raises RuntimeError with a clear message if not configured — this is
    intentional: a missing secret means all tickets would be forgeable.
    """
    raw = os.environ.get(_ZT_SECRET_ENV)
    if not raw:
        raise RuntimeError(
            f"Zero-trust secret not configured. "
            f"Set the {_ZT_SECRET_ENV} environment variable to a strong random secret."
        )
    return raw.encode("utf-8")


def _canonical_payload(project_path: str, file_path: str, action: str, issued_at: str) -> str:
    """
    Canonical JSON string for HMAC signing.
    """
    payload = {
        "project_path": os.path.abspath(os.path.expanduser(project_path)),
        "file_path": os.path.abspath(os.path.expanduser(file_path)),
        "action": action,
        "issued_at": issued_at,
    }
    # Sort keys to ensure deterministic serialization
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sign(payload: str) -> str:
    secret = _get_secret()
    mac = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()


def issue_ticket(project_path: str, file_path: str, action: str) -> Dict[str, Any]:
    """
    Issue a signed ticket for a given action on a file.

    Returns the full ticket dict including signature.
    """
    issued_at = datetime.now(timezone.utc).isoformat()
    payload_str = _canonical_payload(project_path, file_path, action, issued_at)
    sig = _sign(payload_str)

    ticket = json.loads(payload_str)
    ticket["signature"] = sig
    return ticket


def _extract_core_fields(ticket: Dict[str, Any]) -> Tuple[str, str, str, str]:
    """
    Extract core fields needed for verification, or raise ValueError.
    """
    try:
        project_path = ticket["project_path"]
        file_path = ticket["file_path"]
        action = ticket["action"]
        issued_at = ticket["issued_at"]
    except KeyError as e:
        raise ValueError(f"missing field in ticket: {e}")

    return (
        os.path.abspath(os.path.expanduser(str(project_path))),
        os.path.abspath(os.path.expanduser(str(file_path))),
        str(action),
        str(issued_at),
    )


def verify_ticket(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verify that the ticket's signature matches the payload.

    Returns:
        {
            "ok": bool,
            "reason": str | None,
            "project_path": "...",
            "file_path": "...",
            "action": "...",
            "issued_at": "...",
        }
    """
    if not isinstance(ticket, dict):
        return {
            "ok": False,
            "reason": "ticket must be a JSON object",
        }

    try:
        project_path, file_path, action, issued_at = _extract_core_fields(ticket)
    except ValueError as e:
        return {
            "ok": False,
            "reason": str(e),
        }

    provided_sig = ticket.get("signature")
    if not isinstance(provided_sig, str):
        return {
            "ok": False,
            "reason": "missing or invalid signature",
            "project_path": project_path,
            "file_path": file_path,
            "action": action,
            "issued_at": issued_at,
        }

    payload_str = _canonical_payload(project_path, file_path, action, issued_at)
    expected_sig = _sign(payload_str)

    if not hmac.compare_digest(provided_sig, expected_sig):
        return {
            "ok": False,
            "reason": "signature mismatch",
            "project_path": project_path,
            "file_path": file_path,
            "action": action,
            "issued_at": issued_at,
        }

    return {
        "ok": True,
        "reason": None,
        "project_path": project_path,
        "file_path": file_path,
        "action": action,
        "issued_at": issued_at,
    }

