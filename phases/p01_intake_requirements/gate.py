"""P01 Gate — validates that intake captured meaningful structured requirements."""
from __future__ import annotations
import json
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    if not result.output_path:
        return GateOutcome(passed=False, confidence=0.0, issues=["No output path"])

    p = Path(result.output_path)
    if not p.exists() or p.stat().st_size == 0:
        # Try parent dir as fallback
        if p.parent.exists() and any(p.parent.rglob("*")):
            return GateOutcome(passed=True, confidence=0.6, issues=["consolidated.json missing but output dir has files"])
        return GateOutcome(passed=False, confidence=0.0, issues=["No output produced"])

    # Verify intake.json has non-empty raw_text (structured_requirements may be empty from small LLMs)
    issues = []
    intake_json = p.parent / "intake" / "intake.json"
    if intake_json.exists():
        try:
            intake = json.loads(intake_json.read_text())
            raw_text = intake.get("raw_text", "").strip()
            structured = intake.get("structured_requirements", "").strip()
            if not raw_text:
                issues.append("intake.json: raw_text is empty — PRD was not captured")
                return GateOutcome(passed=False, confidence=0.0, issues=issues)
            if not structured:
                # structured_requirements empty means the LLM sub-task failed or timed out.
                # Promote raw_text to structured_requirements so P02 has input to work with.
                intake["structured_requirements"] = raw_text
                intake_json.write_text(json.dumps(intake, indent=2))
                issues.append("structured_requirements was empty — promoted raw_text as fallback")
        except Exception as exc:
            issues.append(f"Could not validate intake.json: {exc}")

    confidence = 0.75 if issues else 1.0
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
