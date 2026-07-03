"""P02 Gate — validate architecture completeness."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)


class ArchitectureGate:
    def validate(self, result: Any) -> GateOutcome:
        # Handle both dict and TaskResult
        if isinstance(result, dict):
            output_path = result.get("output_path", "")
            json_path = result.get("json_path", "")
        else:
            output_path = result.output_path
            json_path = result.metadata.get("json_path", "")

        # Logic for local model runs: lower the bar
        if not output_path or not Path(output_path).exists():
            return GateOutcome(
                passed=False,
                confidence=0.0,
                issues=["architecture output files not written"])

        target_json = Path(json_path) if json_path else Path(output_path)
        if not target_json.exists() or target_json.suffix != ".json":
            # Try to find the json in same directory
            target_json = Path(output_path).parent / "architecture.json"

        if not target_json.exists():
            return GateOutcome(passed=False, issues=["architecture.json not found"])

        try:
            with open(target_json) as f:
                data = json.load(f)
            
            tech_stack = data.get("tech_stack", {})
            api_endpoints = data.get("api_endpoints", [])
            
            issues = []
            # REQUIREMENT: tech_stack exists with at least 3 keys
            if not isinstance(tech_stack, dict) or len(tech_stack.keys()) < 3:
                issues.append(f"tech_stack too sparse ({len(tech_stack) if isinstance(tech_stack, dict) else 0} keys, need >= 3)")
            
            # REQUIREMENT: api_endpoints list is not empty
            if not isinstance(api_endpoints, list) or len(api_endpoints) == 0:
                issues.append("api_endpoints list is empty")

            passed = len(issues) == 0
            return GateOutcome(
                passed=passed,
                confidence=1.0 if passed else 0.2,
                issues=issues
            )
        except Exception as e:
            logger.warning("p02_architecture gate validation failed: %s", e)
            return GateOutcome(
                passed=False,
                confidence=0.0,
                issues=[str(e)])


def validate(result: TaskResult) -> GateOutcome:
    """Standalone validate function for supervisor compatibility."""
    return ArchitectureGate().validate(result)
