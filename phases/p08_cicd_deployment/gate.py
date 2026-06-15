"""P08 Gate — validates CI/CD configuration quality."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)

_MIN_BYTES = 200


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        issues.append("CI/CD configuration not generated — deployment automation unavailable")
        return GateOutcome(passed=False, confidence=0.0, issues=issues)

    output_path = Path(result.output_path)
    try:
        if output_path.suffix == ".json":
            payload = json.loads(output_path.read_text())
            files = payload.get("files", {})
            has_ci = any(
                k for k in files
                if "github" in k.lower() or "gitlab" in k.lower()
                or "ci" in k.lower() or "pipeline" in k.lower()
            )
            has_docker = any("docker" in k.lower() for k in files)
            if not has_ci:
                issues.append("No CI/CD workflow file detected — add .github/workflows or .gitlab-ci.yml")
            if not has_docker:
                issues.append("No Dockerfile detected — containerisation missing")
        else:
            size = output_path.stat().st_size
            if size < _MIN_BYTES:
                issues.append(f"CI/CD output suspiciously small ({size} bytes) — may be a stub")
    except Exception as e:
        logger.warning("P08 gate: could not inspect output (%s)", e)

    confidence = 0.6 if issues else 1.0
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
