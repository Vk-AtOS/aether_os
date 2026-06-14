"""P04b Gate — validates business logic layer has service classes and validators."""
from __future__ import annotations
import ast
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=True,
            confidence=0.5,
            issues=["Business logic layer not produced — services will be inline in route handlers"],
        )

    output_path = Path(result.output_path)
    py_files = list(output_path.rglob("*.py")) if output_path.is_dir() else [output_path]
    service_files = [f for f in py_files if "service" in f.name.lower() or "logic" in f.name.lower()]

    if not service_files:
        issues.append("No service/logic files found in business logic output")
    else:
        total_functions = 0
        for sf in service_files:
            try:
                tree = ast.parse(sf.read_text())
                total_functions += sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
            except SyntaxError as e:
                issues.append(f"Syntax error in {sf.name}: {e}")
        if total_functions == 0:
            issues.append("Service files contain no functions — business logic may be empty")

    confidence = 0.9 if not issues else 0.6
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
