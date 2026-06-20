"""
P21 SRE Agent Gate — prerequisite check before generating SRE operator artifacts.

Passes when deployment_config or architecture data is available from prior phases.
These are written by p08_cicd_deployment and p02_architecture respectively.
"""
from __future__ import annotations

from typing import Any, Tuple


async def check(phase_input: Any) -> Tuple[bool, str]:
    """Return (passed, reason) — gate passes when prior phase outputs are present."""
    data = getattr(phase_input, "input_data", {}) or {}
    if not data.get("deployment_config") and not data.get("architecture"):
        return False, "P21 requires deployment_config or architecture from prior phases"
    return True, "ok"
