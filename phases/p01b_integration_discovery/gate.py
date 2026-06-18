"""P01b Gate — validates integration discovery found and documented external systems."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=True,
            confidence=0.5,
            issues=["Integration discovery produced no output — external systems will not be auto-wired"],
        )

    output_path = Path(result.output_path)
    try:
        candidates = (
            [output_path] if output_path.suffix == ".json"
            else list(output_path.rglob("integrations*.json")) + list(output_path.rglob("integration_map*.json"))
        )
        if candidates and candidates[0].exists():
            data = json.loads(candidates[0].read_text())
            integrations = data if isinstance(data, list) else data.get("integrations", [])
            if not integrations:
                issues.append("No external integrations identified — if the app has third-party services, discovery may have missed them")
    except Exception as exc:
        logger.debug("p01b gate: integration file parse failed (non-fatal): %s", exc)

    confidence = 0.85 if not issues else 0.65
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
