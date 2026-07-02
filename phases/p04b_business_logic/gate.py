"""P04b Gate — validates business logic layer has service classes and validators.

Also checks p04a confidence and pre-gen warnings from accumulated_context,
flagging conservative (template-only) mode when upstream confidence is low.
"""
from __future__ import annotations
import ast
import logging
from pathlib import Path
from typing import Any, Optional

from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)

_LOW_CONFIDENCE_THRESHOLD = 0.6


def validate(result: TaskResult, phase_input: Optional[Any] = None) -> GateOutcome:
    issues: list[str] = []
    context_flags: dict = {}

    # ── Confidence gate: check upstream p04a confidence ───────────────────────
    # phase_input.input_data holds the accumulated_context for this run
    if phase_input is not None:
        try:
            data: dict = getattr(phase_input, "input_data", {}) or {}

            # Check p04_backend phase confidence from accumulated_context
            phase_confidence: dict = data.get("phase_confidence", {})
            p04_conf_entry = phase_confidence.get("p04_backend", {}) or phase_confidence.get("p04a_backend_codegen", {})
            p04_confidence = float(p04_conf_entry.get("confidence", 1.0)) if isinstance(p04_conf_entry, dict) else 1.0

            if p04_confidence < _LOW_CONFIDENCE_THRESHOLD:
                warn_msg = (
                    f"p04a ran with low confidence ({p04_confidence:.2f} < {_LOW_CONFIDENCE_THRESHOLD}) — "
                    "p04b should use conservative (template-only) generation mode"
                )
                issues.append(warn_msg)
                context_flags["conservative_mode"] = True
                context_flags["p04_backend_confidence"] = p04_confidence
                logger.warning("p04b gate: %s", warn_msg)

            # Pass pre-gen warnings forward as context
            pre_gen_warnings: list = data.get("pre_gen_warnings", [])
            if pre_gen_warnings:
                context_flags["pre_gen_warnings"] = pre_gen_warnings
                issues.append(
                    f"{len(pre_gen_warnings)} pre-generation warning(s) from upstream: "
                    + "; ".join(str(w) for w in pre_gen_warnings[:3])
                )
                logger.warning("p04b gate: %d pre_gen_warnings forwarded", len(pre_gen_warnings))

            # Write flags back into phase_input so task_agent can read them
            if context_flags:
                data["p04b_gate_flags"] = context_flags

        except Exception as exc:
            logger.warning("p04b gate: confidence check failed (non-fatal): %s", exc)

    # ── Structural validation: check that service files were produced ──────────
    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=True,
            confidence=0.5,
            issues=issues + ["Business logic layer not produced — services will be inline in route handlers"],
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
                total_functions += sum(
                    1 for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
            except SyntaxError as e:
                issues.append(f"Syntax error in {sf.name}: {e}")
        if total_functions == 0:
            issues.append("Service files contain no functions — business logic may be empty")

    confidence = 0.9 if not issues else 0.6
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
