"""Context schema — advisory validation for accumulated_context dict.

Validates that required keys are present and that each completed phase
placed its expected outputs into the context.  Validation is always
non-fatal: warnings are logged but the pipeline is never halted.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

REQUIRED_KEYS = {
    "run_id", "org_id", "domain", "raw_input", "project_dir",
}

PHASE_OUTPUTS = {
    "p01_intake_requirements": {"requirements", "entities", "api_endpoints"},
    "p02b_domain_ir": {"domain_ir"},
    "p04_backend": {"backend_output_path"},
    "p05_frontend": {"frontend_output_path"},
    "p07b_self_healing": {"healing_passed"},
}


def validate_context(ctx: dict, phase_name: Optional[str] = None) -> list[str]:
    """Return list of missing-key warning strings.  Never raises."""
    warnings: list[str] = []
    for k in REQUIRED_KEYS:
        if k not in ctx:
            warnings.append(f"accumulated_context missing required key: '{k}'")
    if phase_name and phase_name in PHASE_OUTPUTS:
        for k in PHASE_OUTPUTS[phase_name]:
            if k not in ctx:
                warnings.append(
                    f"after {phase_name}: expected key '{k}' not found in context"
                )
    return warnings


def assert_context(ctx: dict, phase_name: Optional[str] = None) -> None:
    """Log warnings but never raise — context validation is advisory."""
    for w in validate_context(ctx, phase_name):
        logger.warning("[context_schema] %s", w)
