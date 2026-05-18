"""P08 Gate — validate CI/CD repair or proactive scan results."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, List, Dict
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)

class CICDGate:
    def validate(self, result: Any) -> GateOutcome:
        # Handle both dict and TaskResult
        if isinstance(result, dict):
            output_path = result.get("output_path", "")
        else:
            output_path = result.output_path

        if not output_path or not Path(output_path).exists():
            return GateOutcome(
                passed=False,
                confidence=0.0,
                issues=["CI/CD output directory not found"])

        path = Path(output_path)
        
        # REQUIREMENT 1: cicd_patch.diff exists (repair mode)
        if (path / "cicd_patch.diff").exists():
            return GateOutcome(passed=True, confidence=0.9, issues=[])
            
        # REQUIREMENT 2: scan_report.json exists (scan mode)
        if (path / "scan_report.json").exists():
            try:
                with open(path / "scan_report.json") as f:
                    report = json.load(f)
                return GateOutcome(passed=True, confidence=0.8, issues=[])
            except Exception as _e:
                logger.warning("Failed to parse scan_report.json in p08 gate: %s", _e)
                
        # REQUIREMENT 3: ci.yml was generated (minimum viable)
        if (path / "ci.yml").exists():
            return GateOutcome(passed=True, confidence=0.6, issues=[])

        return GateOutcome(
            passed=False,
            confidence=0.0,
            issues=["No valid CI/CD outputs (patch, scan report, or ci.yml) found"])

def validate(result: TaskResult) -> GateOutcome:
    """Standalone validate function for supervisor compatibility."""
    return CICDGate().validate(result)
