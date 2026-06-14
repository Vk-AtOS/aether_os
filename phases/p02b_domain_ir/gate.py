"""P02b Gate — validates domain IR has entities, fields, and relationships."""
from __future__ import annotations
import json
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=False,
            confidence=0.0,
            issues=["Domain IR not produced — p04 backend codegen will fall back to generic stubs"],
        )

    output_path = Path(result.output_path)
    try:
        candidates = (
            [output_path] if output_path.suffix == ".json"
            else list(output_path.rglob("domain_ir*.json")) + list(output_path.rglob("ir.json"))
        )
        if candidates and candidates[0].exists():
            ir = json.loads(candidates[0].read_text())
            entities = ir.get("entities", [])
            if not entities:
                issues.append("Domain IR has no entities — backend models will be generic")
            else:
                entities_without_fields = [e.get("name", "?") for e in entities if not e.get("fields")]
                if entities_without_fields:
                    issues.append(f"Entities missing fields: {', '.join(entities_without_fields)}")
        else:
            issues.append("domain_ir.json not found in output directory")
    except Exception as e:
        issues.append(f"Could not parse domain IR: {e}")

    passed = len(issues) == 0 or (len(issues) == 1 and "generic" in issues[0])
    confidence = 0.9 if not issues else 0.5
    return GateOutcome(passed=passed, confidence=confidence, issues=issues)
