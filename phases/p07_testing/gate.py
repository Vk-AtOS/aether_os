"""AetherOS — Phase 07 Testing Gate"""
from __future__ import annotations
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class GateResult:
    def __init__(self, passed: bool, issues: List[str], confidence: float = 1.0):
        self.passed = passed
        self.issues = issues
        self.confidence = confidence

    def to_dict(self) -> Dict[str, Any]:
        return {"passed": self.passed, "issues": self.issues, "confidence": self.confidence}


def validate(test_results: Dict[str, Any]) -> GateResult:
    issues: List[str] = []
    if not test_results.get("test_code"):
        issues.append("No test code generated")
    passed = test_results.get("passed", True) and len(issues) == 0
    return GateResult(passed=passed, issues=issues, confidence=0.8 if passed else 0.2)
