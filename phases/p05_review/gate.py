"""AetherOS — Phase 05 Review Gate"""
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


def validate(review_findings: List[str], quality_score: float = 7.0) -> GateResult:
    issues: List[str] = []
    critical = [f for f in review_findings if "critical" in f.lower() or "CRITICAL" in f]
    if critical:
        issues.extend(critical[:5])
    passed = len(issues) == 0 and quality_score >= 5.0
    confidence = quality_score / 10.0
    return GateResult(passed=passed, issues=issues, confidence=confidence)
