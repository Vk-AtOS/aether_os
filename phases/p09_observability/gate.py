"""P09 Gate — validates observability configuration is present.

Observability is non-blocking (passes even if incomplete) but surfaces
actionable issues so the operator knows what's missing.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)

_EXPECTED_KEYS = {"logging", "metrics", "tracing", "alerts"}


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=True,
            confidence=0.5,
            issues=["Observability config not written — logging/metrics/tracing setup required manually"],
        )

    try:
        payload = json.loads(Path(result.output_path).read_text())
        present = {k for k in _EXPECTED_KEYS if payload.get(k)}
        missing = _EXPECTED_KEYS - present
        if missing:
            issues.append(f"Missing observability components: {', '.join(sorted(missing))}")
    except Exception as exc:
        # Non-JSON output (e.g. YAML config) — treat as present
        logger.debug("p09 gate: output_path parse failed (non-fatal, treating as present): %s", exc)

    confidence = 1.0 if not issues else 0.65
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
