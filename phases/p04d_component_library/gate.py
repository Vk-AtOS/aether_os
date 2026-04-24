"""P04d Gate."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

def validate(result: TaskResult) -> GateOutcome:
    if not result.output_path:
        return GateOutcome(passed=False, issues=["No output"])
    stories_dir = Path(result.output_path)
    if not stories_dir.exists():
        return GateOutcome(passed=False, issues=["stories directory not created"])
    story_count = result.metadata.get("story_count", 0)
    component_count = result.metadata.get("component_count", 1)
    issues = []
    if story_count < component_count:
        issues.append(f"story_count {story_count} < component_count {component_count}")
    return GateOutcome(passed=len(issues)==0, issues=issues, confidence=0.85)
