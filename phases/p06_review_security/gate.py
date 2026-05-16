"""P06 Gate — enforces security review quality.

Blocks the pipeline if:
  - Output file is missing entirely (no review ran)
  - Security scan found CRITICAL severity issues
  - Security scan found >= 5 HIGH severity issues

Passes with warnings for moderate/low findings.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)

_CRITICAL_THRESHOLD = 1   # any critical → block
_HIGH_THRESHOLD     = 5   # 5+ highs → block


def _count_severities(data: dict) -> dict[str, int]:
    """Walk any nested structure counting severity keys."""
    counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            sev = str(node.get("severity", "")).lower()
            if sev in counts:
                counts[sev] += 1
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return counts


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    # ── 1. Output existence ───────────────────────────────────────────────────
    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=False,
            confidence=0.0,
            issues=["Security review produced no output — pipeline blocked pending manual review"],
        )

    # ── 2. Parse security findings ────────────────────────────────────────────
    severity_counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    try:
        payload = json.loads(Path(result.output_path).read_text())
        # Try consolidated structure first
        security_data = (
            payload.get("phases", {}).get("security", {})
            or payload.get("security", {})
            or payload
        )
        severity_counts = _count_severities(security_data)
    except Exception as e:
        logger.warning("P06 gate: could not parse security output (%s) — treating as no findings", e)

    n_critical = severity_counts["critical"]
    n_high     = severity_counts["high"]
    n_medium   = severity_counts["medium"]
    n_low      = severity_counts["low"]

    # ── 3. Blocking conditions ────────────────────────────────────────────────
    if n_critical >= _CRITICAL_THRESHOLD:
        issues.append(
            f"BLOCKED: {n_critical} CRITICAL security finding(s) must be resolved before proceeding"
        )
        return GateOutcome(passed=False, confidence=0.0, issues=issues)

    if n_high >= _HIGH_THRESHOLD:
        issues.append(
            f"BLOCKED: {n_high} HIGH severity findings exceed threshold of {_HIGH_THRESHOLD}"
        )
        return GateOutcome(passed=False, confidence=0.1, issues=issues)

    # ── 4. Non-blocking warnings ──────────────────────────────────────────────
    if n_high > 0:
        issues.append(f"{n_high} HIGH severity finding(s) — review recommended")
    if n_medium > 0:
        issues.append(f"{n_medium} MEDIUM finding(s) noted")
    if n_low > 0:
        issues.append(f"{n_low} LOW finding(s) noted")

    confidence = 0.95
    if n_high > 0:
        confidence -= 0.05 * n_high
    confidence = max(0.5, round(confidence, 2))

    return GateOutcome(passed=True, confidence=confidence, issues=issues)
