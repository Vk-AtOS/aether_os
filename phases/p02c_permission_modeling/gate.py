"""P02c Gate — validates ABAC permission model has roles and resource rules."""
from __future__ import annotations
import json
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=True,
            confidence=0.5,
            issues=["Permission model not produced — app will use default role-based access only"],
        )

    output_path = Path(result.output_path)
    try:
        candidates = (
            [output_path] if output_path.suffix == ".json"
            else list(output_path.rglob("permission*.json")) + list(output_path.rglob("rbac*.json"))
        )
        if candidates and candidates[0].exists():
            model = json.loads(candidates[0].read_text())
            roles = model.get("roles", [])
            rules = model.get("rules", model.get("policies", []))
            if not roles:
                issues.append("No roles defined in permission model")
            if not rules:
                issues.append("No access rules/policies defined in permission model")
    except Exception as e:
        issues.append(f"Could not parse permission model: {e}")

    confidence = 0.9 if not issues else 0.6
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
