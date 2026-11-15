"""Classify a prompt as sensitive BEFORE a provider is chosen (D6).

Sensitive prompts (credentials, card numbers, government ids, bulk personal contact data) may only
go to providers the operator has a data agreement with: never to community/free endpoints, which
may log or train on what they receive. This is a pattern screen, not a guarantee: it catches the
obvious shapes and errs towards "sensitive" (the cost of a false positive is a slower provider).
"""
from __future__ import annotations

import re
from typing import List

_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "api_token": re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test|ant|proj)?[-_]?[A-Za-z0-9]{20,}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
    "credential_assignment": re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*[\"']?[^\s\"']{8,}"),
    "us_ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "aadhaar": re.compile(r"\b[2-9]\d{3}\s\d{4}\s\d{4}\b"),
}
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_BULK_EMAILS = 3


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def classify(*texts: str) -> List[str]:
    """Reasons the text is sensitive (empty list = nothing found). Never returns the matched text."""
    text = "\n".join(t for t in texts if t)
    reasons = [name for name, rx in _PATTERNS.items() if rx.search(text)]
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            reasons.append("card_number")
            break
    if len(set(_EMAIL.findall(text))) >= _BULK_EMAILS:
        reasons.append("bulk_personal_data")
    return reasons
