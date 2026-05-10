"""
AetherOS — Code Quality Evaluator (D5)

Scores generated code on syntax, security (bandit), and basic quality metrics.
Called after p04a_backend_codegen produces main.py.
"""
from __future__ import annotations

import ast
import json
import logging
import subprocess
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def score_generated_code(
    requirement: str,
    generated_code: str,
    run_id: str,
) -> Dict[str, Any]:
    """Return a quality score dict for a generated code string."""
    # Syntax check
    try:
        ast.parse(generated_code)
        syntax_ok = True
        syntax_error = None
    except SyntaxError as exc:
        return {
            "syntax_ok": False,
            "error": str(exc),
            "security_score": 0,
            "security_issues": 0,
            "high_severity_issues": 0,
            "overall": 0,
        }

    # Security scan via bandit
    security_issues = 0
    high_severity = 0
    try:
        result = subprocess.run(
            ["bandit", "-r", "-f", "json", "-"],
            input=generated_code,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout:
            bandit_data = json.loads(result.stdout)
            findings = bandit_data.get("results", [])
            security_issues = len(findings)
            high_severity = sum(
                1 for r in findings if r.get("issue_severity") == "HIGH"
            )
    except FileNotFoundError:
        logger.debug("bandit not installed — skipping security scan")
    except Exception as exc:
        logger.debug("bandit scan failed: %s", exc)

    # Complexity heuristic: count functions/classes
    try:
        tree = ast.parse(generated_code)
        func_count = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        class_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    except Exception:
        func_count = 0
        class_count = 0

    # Line count
    line_count = generated_code.count("\n")

    # Overall score: start at 100, deduct for issues
    security_score = max(0, 100 - (high_severity * 20) - (security_issues * 5))
    overall = security_score

    return {
        "syntax_ok": syntax_ok,
        "security_score": security_score,
        "security_issues": security_issues,
        "high_severity_issues": high_severity,
        "function_count": func_count,
        "class_count": class_count,
        "line_count": line_count,
        "overall": overall,
    }
