"""Credential shapes shared by the detectors (security_web, prodready) and by snippet redaction (base).

Kept dependency-free so base.py can import it without a cycle.
"""
import re

# (pattern, label, severity). Shapes of real provider credentials; test-mode keys are lower severity.
KEY_FORMATS = (
    (re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"), "AWS access key id", "critical"),
    (re.compile(r"\b[rs]k_live_[0-9a-zA-Z]{16,}"), "Stripe live key", "critical"),
    (re.compile(r"\bsk_test_[0-9a-zA-Z]{16,}"), "Stripe test key", "medium"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "Google API key", "high"),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"), "GitHub token", "critical"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token", "high"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic API key", "critical"),
    (re.compile(r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{32,}"), "OpenAI-style API key", "critical"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "JWT literal", "medium"),
)
CRED_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://([^/\s:@'\"]+):([^/\s:@'\"]+)@")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")
