"""Redact credentials from text that will be stored or shown to a user.

Exception messages routinely carry connection URLs, request headers and keys.
`redact_secrets` is the one place such text is cleaned before it leaves a log.
"""
from __future__ import annotations

import re
from typing import Optional

_MASK = "[redacted]"

_RULES = [
    # scheme://user:password@host  →  scheme://[redacted]@host
    (re.compile(r"\b([a-z][a-z0-9+.\-]*://)[^/\s@]+@", re.I), r"\1" + _MASK + "@"),
    # Authorization values
    (re.compile(r"\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}", re.I), r"\1 " + _MASK),
    # JSON Web Tokens
    (re.compile(r"\beyJ[\w\-]{8,}\.[\w\-]{8,}\.[\w\-]{8,}"), _MASK),
    # Provider key shapes: OpenAI/Anthropic/OpenRouter/Stripe sk-…, AetherOS aesk_…,
    # Razorpay, AWS access key ids, Google, GitHub, Slack.
    (re.compile(
        r"\b(?:sk-[\w\-]{16,}|[sr]k_(?:live|test)_\w{10,}|aesk_[\w\-]{8,}|rzp_(?:live|test)_\w{8,}"
        r"|A[KS]IA[0-9A-Z]{16}|AIza[\w\-]{30,}|gh[pousr]_\w{20,}|xox[abprs]-[\w\-]{10,})"), _MASK),
    # name=value / "name": "value" for credential-like names
    (re.compile(
        r"\b((?:api[_-]?key|access[_-]?key|secret(?:[_-]?key)?|token|password|passwd|pwd|authorization)"
        r"[\"']?\s*[:=]\s*[\"']?)[^\s\"',;&)]{4,}", re.I), r"\1" + _MASK),
    # ponytail: long-secret heuristic — an unbroken 32+ run of letters AND digits (hex
    # digests, base64 keys). No "-" or "/" in the class so UUIDs and file paths survive;
    # a secret containing those is only caught by the rules above.
    (re.compile(r"\b(?=[A-Za-z0-9+_=]*\d)(?=[A-Za-z0-9+_=]*[A-Za-z])[A-Za-z0-9+_=]{32,}"), _MASK),
]


def redact_secrets(text: Optional[object], limit: int = 500) -> str:
    """Return `text` with credentials masked, capped at `limit` characters."""
    out = "" if text is None else str(text)
    for pattern, replacement in _RULES:
        out = pattern.sub(replacement, out)
    return out if len(out) <= limit else out[: limit - 1] + "…"
