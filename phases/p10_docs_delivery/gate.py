"""P10 Gate — validates documentation completeness.

Non-blocking but enforces minimum content quality standards.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)

_MIN_README_BYTES  = 500    # a real README is at least 500 bytes
_EXPECTED_SECTIONS = {"setup", "api", "architecture", "deployment"}


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=True,
            confidence=0.4,
            issues=["Documentation not generated — README.md and API docs are required for handoff"],
        )

    output_path = Path(result.output_path)
    try:
        if output_path.suffix == ".json":
            payload = json.loads(output_path.read_text())
            files = payload.get("files", {})
            readme = next((v for k, v in files.items() if "readme" in k.lower()), None)
            if readme is None:
                issues.append("README.md missing from documentation output")
            elif len(readme) < _MIN_README_BYTES:
                issues.append(f"README.md is too short ({len(readme)} chars) — expand with setup and usage sections")
            else:
                readme_lower = readme.lower()
                missing_secs = [s for s in _EXPECTED_SECTIONS if s not in readme_lower]
                if missing_secs:
                    issues.append(f"README may be missing sections: {', '.join(missing_secs)}")
            if not any("api" in k.lower() for k in files):
                issues.append("No API reference documentation found")
        else:
            size = output_path.stat().st_size
            if size < _MIN_README_BYTES:
                issues.append(f"Documentation output is too small ({size} bytes)")
    except Exception as e:
        logger.warning("P10 gate: could not inspect docs content (%s)", e)

    confidence = 0.9 if not issues else 0.7
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
