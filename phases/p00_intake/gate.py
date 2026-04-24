"""P00 Gate — validate intake record completeness."""
from __future__ import annotations
import json
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    output_path = result.output_path
    
    if not output_path or not Path(output_path).exists():
        return GateOutcome(
            passed=False,
            confidence=0.0,
            issues=["intake.json not written"])
    
    try:
        with open(output_path) as f:
            data = json.load(f)
        raw_text = data.get("raw_text", data.get("content", ""))
        if len(raw_text.split()) >= 3:
            return GateOutcome(
                passed=True,
                confidence=0.9,
                issues=[])
        return GateOutcome(
            passed=False,
            confidence=0.2,
            issues=["Input too short"])
    except Exception as e:
        return GateOutcome(
            passed=False,
            confidence=0.0,
            issues=[str(e)])
