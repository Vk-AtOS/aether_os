"""
AetherOS — Phase Failure Router
NEW module. Routes pipeline failures back to the correct phase for retry.

Maps failure types (from gate results) to the phase that should re-run.
"""
from __future__ import annotations
import logging
from typing import Dict, Optional

from aether_os.orchestrator.state_machine import PipelineState

logger = logging.getLogger(__name__)

# Failure type → target phase to retry
_FAILURE_ROUTING: Dict[str, PipelineState] = {
    "security_critical": PipelineState.BACKEND_CODEGEN,
    "security_high": PipelineState.BACKEND_CODEGEN,
    "test_failure": PipelineState.BACKEND_CODEGEN,
    "syntax_error": PipelineState.BACKEND_CODEGEN,
    "review_critical": PipelineState.BACKEND_CODEGEN,
    "architecture_incomplete": PipelineState.ARCHITECTURE,
    "requirements_unclear": PipelineState.REQUIREMENTS,
    "ci_failure": PipelineState.BACKEND_CODEGEN,
    "docs_missing": PipelineState.DOCUMENTATION,
    "packaging_failure": PipelineState.DEPLOYMENT,
}


def route_failure(
    failure_type: str,
    current_phase: PipelineState,
) -> Optional[PipelineState]:
    """
    Determine which phase to route back to given a failure type.

    Args:
        failure_type: String key describing the failure category.
        current_phase: The phase where the failure occurred.

    Returns:
        The target phase to retry, or None if the failure is unrecoverable.
    """
    target = _FAILURE_ROUTING.get(failure_type)
    if target is None:
        logger.warning(
            "Unknown failure type '%s' at phase %s — no automatic routing",
            failure_type, current_phase.value,
        )
        return None

    # Don't route forward (only backward or same phase)
    try:
        from aether_os.orchestrator.state_machine import PIPELINE_SEQUENCE
        current_idx = PIPELINE_SEQUENCE.index(current_phase) if current_phase in PIPELINE_SEQUENCE else 99
        target_idx = PIPELINE_SEQUENCE.index(target) if target in PIPELINE_SEQUENCE else 99
        if target_idx > current_idx:
            logger.warning("Router tried to route forward (%s→%s), refusing", current_phase, target)
            return None
    except Exception as exc:
        logger.debug("Phase sequence check failed (non-fatal): %s", exc)

    logger.info("Routing failure '%s' from %s → %s", failure_type, current_phase.value, target.value)
    return target
