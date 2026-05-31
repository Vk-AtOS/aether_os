"""P04b Gate — validates UI/UX design output."""
from __future__ import annotations
import json
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    # Prefer json_path from metadata; fall back to output_path
    json_path = Path(result.metadata.get("json_path", "") if result.metadata else "")
    if not json_path or not json_path.exists():
        json_path = Path(result.output_path or "")

    if not json_path.exists():
        return GateOutcome(passed=False, confidence=0.0,
                           issues=["Design output file not found"])

    try:
        data = json.loads(json_path.read_text())
    except Exception:
        return GateOutcome(passed=True, confidence=0.5,
                           issues=["Design output is not JSON — may be a wireframe doc"])

    if not data.get("pages"):
        issues.append("No pages defined in design output")
    if not data.get("component_inventory"):
        issues.append("component_inventory missing — UI components not listed")

    if any(k in issues for k in ["No pages", "component_inventory"]):
        return GateOutcome(passed=False, confidence=0.1, issues=issues)

    return GateOutcome(passed=True, confidence=0.9 if not issues else 0.7, issues=issues)
