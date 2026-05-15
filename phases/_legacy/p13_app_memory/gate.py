from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import TaskResult, GateOutcome

async def validate(result: TaskResult, phase_input: Any) -> GateOutcome:
    issues = list(result.issues)
    output = Path(result.output_path)
    if not (output / "memory_service.py").exists():
        issues.append("memory_service.py missing")
    if not (output / "knowledge_graph.py").exists():
        issues.append("knowledge_graph.py missing")
    if not (output.parent / "migrations/add_memory.sql").exists():
        issues.append("add_memory.sql missing")
    return GateOutcome(passed=len(issues) == 0, issues=issues, confidence=result.confidence)
