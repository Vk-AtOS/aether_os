"""AetherOS — Phase 04 Codegen Gate"""
from __future__ import annotations
import ast
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


def validate(code: str) -> GateResult:
    issues: List[str] = []
    if not code or not code.strip():
        issues.append("Generated code is empty")
        return GateResult(passed=False, issues=issues, confidence=0.0)

    if len(code.strip()) < 50:
        issues.append(f"Generated code suspiciously short ({len(code)} chars)")

    # Try Python syntax check
    try:
        ast.parse(code)
    except SyntaxError as exc:
        issues.append(f"Python syntax error: {exc}")

    passed = len(issues) == 0
    confidence = 0.9 if passed else 0.3
    return GateResult(passed=passed, issues=issues, confidence=confidence)
