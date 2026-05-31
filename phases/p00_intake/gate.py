"""P00 Gate — validates that intake captured a meaningful requirement."""
from __future__ import annotations
import json
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

_MIN_RAW_TEXT_LEN = 20


def validate(result: TaskResult) -> GateOutcome:
    p = Path(result.output_path or "")
    if not p.exists():
        return GateOutcome(passed=False, confidence=0.0,
                           issues=["No output file produced by intake phase"])

    try:
        data = json.loads(p.read_text())
    except Exception:
        return GateOutcome(passed=False, confidence=0.0,
                           issues=["Intake output is not valid JSON"])

    raw_text = data.get("raw_text", "").strip()
    if len(raw_text) < _MIN_RAW_TEXT_LEN:
        return GateOutcome(
            passed=False, confidence=0.0,
            issues=[f"raw_text too short ({len(raw_text)} chars) — requirement not captured"],
        )

    issues = []
    if not data.get("structured_requirements", "").strip():
        issues.append("structured_requirements is empty — LLM parsing may have failed")

    return GateOutcome(passed=True, confidence=0.9 if not issues else 0.6, issues=issues)
