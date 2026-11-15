"""
AetherOS — Prompt Injection Guard (B7)

Validates raw_input before it reaches LLM prompts.
Blocks jailbreak attempts and shell injection patterns.
"""
from __future__ import annotations
import re
from typing import Tuple

JAILBREAK_PATTERNS = [
    r'ignore (all |previous |above |prior )?instructions?',
    r'you are now',
    r'act as (if )?you',
    r'disregard (your |all )?',
    r'forget (everything|all|your)',
    r'system prompt',
    r'DAN mode',
    r'developer mode',
    r'bypass (your |all )?',
    r'override (your |all )?',
]

INJECTION_PATTERNS = [
    r'\$\(.*\)',        # shell command substitution
    # Backtick *execution* only: requirements legitimately quote identifiers ("a `status` field").
    r'`\s*(rm|wget|curl|bash|sh|zsh|python3?|nc|ncat|cat|chmod|chown|sudo|eval|env|printenv)\b[^`]*`',
    r';\s*(rm|wget|curl|bash|sh|python|nc)\s',
    r'<script[^>]*>',  # XSS
    r'javascript:',
]


def guard(raw_input: str) -> Tuple[bool, str]:
    """Returns (is_safe, reason). is_safe=True means proceed."""
    if len(raw_input) > 10000:
        return False, "Requirement exceeds 10,000 character limit."
    for pattern in JAILBREAK_PATTERNS:
        if re.search(pattern, raw_input, re.IGNORECASE):
            return False, "Requirement contains disallowed content."
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, raw_input):
            return False, "Requirement contains potentially unsafe content."
    return True, ""
