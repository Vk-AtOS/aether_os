"""P04a Gate — validate backend code syntax and completeness."""
from __future__ import annotations
import ast
import logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)

class BackendCodegenGate:
    def validate(self, result: Any) -> GateOutcome:
        # Handle both dict and TaskResult
        if isinstance(result, dict):
            output_path = result.get("output_path", "")
            generated_files = result.get("generated_files", [])
        else:
            output_path = result.output_path
            generated_files = result.metadata.get("generated_files", [])

        if not output_path or not Path(output_path).exists():
            return GateOutcome(passed=False, issues=["Output directory not found"])

        if not generated_files:
            # Try to find .py files in output_path if list is empty
            generated_files = [str(f) for f in Path(output_path).rglob("*.py")]

        # REQUIREMENT: At least 1 .py file was generated
        if not generated_files:
            return GateOutcome(passed=False, issues=["No .py files were generated"])

        issues = []
        has_functions = False

        for file_path in generated_files:
            p = Path(file_path)
            if not p.exists():
                issues.append(f"File not found: {p.name}")
                continue
            
            content = p.read_text()
            
            # REQUIREMENT: ALL generated .py files pass ast.parse()
            try:
                ast.parse(content)
            except SyntaxError as e:
                issues.append(f"Syntax error in {p.name}: {e}")
            
            # REQUIREMENT: At least one file contains "def " or "async def "
            if "def " in content or "async def " in content:
                has_functions = True

        if not has_functions:
            issues.append("No functions found in generated code")

        passed = len(issues) == 0
        return GateOutcome(
            passed=passed,
            issues=issues,
            confidence=0.9 if passed else 0.3
        )

def validate(result: TaskResult) -> GateOutcome:
    """Standalone validate function for supervisor compatibility."""
    return BackendCodegenGate().validate(result)
