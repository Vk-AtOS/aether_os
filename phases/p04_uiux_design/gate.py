"""P04b Gate — validates UI/UX design output."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    # Prefer json_path from metadata; fall back to output_path
    # (Path("") is "." and exists, so test the strings, and require a file)
    json_path = Path((result.metadata or {}).get("json_path") or "")
    if not json_path.name or not json_path.is_file():
        json_path = Path(result.output_path or "")

    if not json_path.name or not json_path.is_file():
        return GateOutcome(passed=False, confidence=0.0,
                           issues=["Design output file not found"])

    try:
        data = json.loads(json_path.read_text())
    except Exception as e:
        logger.warning("p04_uiux gate: design output is not valid JSON: %s", e)
        return GateOutcome(passed=True, confidence=0.5,
                           issues=["Design output is not JSON — may be a wireframe doc"])

    if not data.get("pages"):
        issues.append("No pages defined in design output")
    # the agent writes "components"; "component_inventory" is the older name
    if not (data.get("components") or data.get("component_inventory")):
        issues.append("components missing — UI components not listed")

    if issues:  # both are required: a design with no pages or no components is unusable
        return GateOutcome(passed=False, confidence=0.1, issues=issues)

    return GateOutcome(passed=True, confidence=0.9 if not issues else 0.7, issues=issues)
