from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import TaskResult, GateOutcome

async def validate(result: TaskResult, phase_input: Any) -> GateOutcome:
    issues = list(result.issues)
    if not result.success:
        issues.append("task_agent reported failure")
    output = Path(result.output_path)
    if not output.exists():
        issues.append(f"output path missing: {result.output_path}")
    
    # Custom Checks
    if not (output / "prometheus.yml").exists():
        issues.append("prometheus.yml missing")
    if len(list((output / "grafana/dashboards").glob("*.json"))) < 3:
        issues.append("less than 3 grafana dashboards found")
    if not (output / "docker-compose.monitoring.yml").exists():
        issues.append("docker-compose.monitoring.yml missing")
        
    return GateOutcome(passed=len(issues) == 0, issues=issues, confidence=result.confidence)
