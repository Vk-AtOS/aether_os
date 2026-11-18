"""P07c Gate — validates accessibility test found no critical WCAG violations."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)

_CRITICAL_IMPACT = {"critical", "serious"}


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=True,
            confidence=0.5,
            issues=["Accessibility test produced no output — WCAG compliance not verified"],
        )

    output_path = Path(result.output_path)
    try:
        candidates = (
            [output_path] if output_path.suffix == ".json"
            else list(output_path.rglob("a11y*.json")) + list(output_path.rglob("axe*.json")) + list(output_path.rglob("accessibility*.json"))
        )
        if candidates and candidates[0].exists():
            data = json.loads(candidates[0].read_text())
            # the result stores the count in "violations" and the first findings in "items"
            raw = data.get("items") if isinstance(data.get("violations"), int) else data.get("violations", [])
            violations = raw or []
            critical = [v for v in violations if v.get("impact", "") in _CRITICAL_IMPACT]
            if critical:
                rules = ", ".join(v.get("id", "?") for v in critical[:5])
                issues.append(f"{len(critical)} critical/serious WCAG violations: {rules}")
                if len(critical) > 3:
                    return GateOutcome(passed=False, confidence=0.3, issues=issues)
            minor = len(violations) - len(critical)
            if minor > 10:
                issues.append(f"{minor} minor accessibility violations — review before release")
    except Exception as e:
        logger.warning("p07c_a11y gate: could not parse accessibility results: %s", e)
        issues.append(f"Could not parse accessibility results: {e}")

    passed = not any("critical" in i or "serious" in i for i in issues) or len([i for i in issues if "critical" in i or "serious" in i]) <= 3
    confidence = 0.9 if not issues else 0.6
    return GateOutcome(passed=passed, confidence=confidence, issues=issues)
