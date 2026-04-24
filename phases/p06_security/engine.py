import re
from typing import Tuple


RISK_PATTERNS = {
    "process": [
        r"\bos\.system\(",
        r"\bsubprocess\.",
    ],
    "eval_exec": [
        r"\beval\(",
        r"\bexec\(",
    ],
    "file_ops": [
        r"\bopen\(",
        r"\bos\.remove\(",
        r"\bos\.rmdir\(",
        r"\bshutil\.rmtree\(",
    ],
    "network": [
        r"\brequests\.",
        r"\burllib\.request\.",
        r"\bsocket\.",
    ],
}


def score_source(source: str) -> Tuple[str, int]:
    """
    Very simple heuristic risk scorer.

    Returns:
        (label, score)

        label: "LOW", "MEDIUM", or "HIGH"
        score: 0–100
    """
    score = 0

    # Basic complexity / size contribution
    lines = [ln for ln in source.splitlines() if ln.strip()]
    if len(lines) > 50:
        score += 10
    if len(lines) > 200:
        score += 20

    # Pattern-based contributions
    for category, patterns in RISK_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, source):
                if category in ("process", "eval_exec"):
                    score += 40
                elif category == "network":
                    score += 25
                elif category == "file_ops":
                    score += 20

    # Clamp to [0, 100]
    score = max(0, min(100, score))

    if score >= 70:
        label = "HIGH"
    elif score >= 30:
        label = "MEDIUM"
    else:
        label = "LOW"

    return label, score

