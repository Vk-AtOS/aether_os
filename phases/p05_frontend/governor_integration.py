"""Governor integration for p05_frontend — called from task_agent after component generation."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run_frontend_governor(
    accumulated_context: dict,
    entity_names: list[str],
    output_dir: Path,
) -> None:
    """Run ArchitectureGovernor on generated frontend component names.

    Updates accumulated_context with violation summary. Non-fatal — all
    errors are caught and logged so the frontend build is never blocked.
    """
    try:
        from aether_os.core.architecture_governor import ArchitectureGovernor
        _gov = ArchitectureGovernor.from_output_dir(output_dir)
        if _gov is None:
            return
        violations = _gov.check_frontend_components(entity_names)
        if violations:
            logger.warning(
                "p05_frontend governor: %d violation(s): %s",
                len(violations),
                [v.detail for v in violations[:3]],
            )
        accumulated_context.setdefault("governor_report_p05", {
            "entity_names_checked": entity_names,
            "violation_count": len(violations),
            "phantom_entities": [
                v.entity_name for v in violations if v.violation_type == "phantom_entity"
            ],
        })
    except Exception as exc:
        logger.warning("p05 governor check failed (non-fatal): %s", exc)
