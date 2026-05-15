"""P04b Gate."""
from __future__ import annotations
import json
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

def validate(result: TaskResult) -> GateOutcome:
    if not result.success or not result.output_path:
        return GateOutcome(passed=False, issues=result.issues or ["Task failed"])
    json_path = Path(result.metadata.get("json_path",""))
    issues = list(result.issues)
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text())
            tokens = data.get("design_tokens",{})
            for k in ["colors","typography","spacing","breakpoints"]:
                if k not in tokens:
                    issues.append(f"design_tokens missing: {k}")
            if len(data.get("component_inventory",[])) < 5:
                issues.append("component_inventory needs >= 5 items")
        except Exception as e:
            issues.append(f"components.json parse error: {e}")
    else:
        issues.append("components.json not found")
    return GateOutcome(passed=len(issues)==0, issues=issues)
