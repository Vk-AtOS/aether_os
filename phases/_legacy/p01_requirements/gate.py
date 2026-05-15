"""P01 Gate — validate requirements document."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, List, Dict
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)


class RequirementsGate:
    def validate(self, result: Any) -> GateOutcome:
        # Handle both dict and TaskResult
        if isinstance(result, dict):
            output_path = result.get("output_path", "")
        else:
            output_path = getattr(result, "output_path", "")

        if not output_path or not Path(output_path).exists():
            return GateOutcome(
                passed=False,
                confidence=0.0,
                issues=["requirements.json not written"])

        try:
            # The task agent now writes JSON to requirements.json
            # and MD to requirements.md. We validate the JSON.
            path = Path(output_path)
            if path.suffix != ".json":
                # Fallback to looking for JSON if MD path was provided
                json_path = path.parent / "requirements.json"
                if json_path.exists():
                    path = json_path
                else:
                    # If only MD exists, check if MD exists
                    md_path = path.parent / "requirements.md"
                    if md_path.exists():
                        return GateOutcome(passed=True, confidence=0.7, issues=[])
                    return GateOutcome(passed=False, confidence=0.0, issues=["No output files found"])

            with open(path) as f:
                data = json.load(f)
            
            func_reqs = data.get("functional_requirements", [])
            acc_crit = data.get("acceptance_criteria", [])
            
            issues = []
            if not isinstance(func_reqs, list) or len(func_reqs) < 2:
                issues.append("Need at least 2 functional requirements")
            if not isinstance(acc_crit, list) or len(acc_crit) < 1:
                issues.append("Need at least 1 acceptance criteria")
            
            passed = len(issues) == 0
            return GateOutcome(
                passed=passed,
                confidence=0.9 if passed else 0.3,
                issues=issues
            )
        except Exception as e:
            return GateOutcome(
                passed=False,
                confidence=0.0,
                issues=[str(e)])


def validate(result: TaskResult) -> GateOutcome:
    """Standalone validate function for supervisor compatibility."""
    return RequirementsGate().validate(result)
