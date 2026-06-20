"""
P17 Control Plane — Kubernetes Operator + CRD generator.

Activated when build_profile.architecture in ("microservices", "event_driven")
or build_profile.deployment_target == "kubernetes".
Generates a complete operator-sdk-style operator for each domain entity.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.phases.p17_control_plane.operator_generator import generate_operator_package

logger = logging.getLogger(__name__)

_TRIGGER_ARCHITECTURES = {"microservices", "event_driven"}
_TRIGGER_TARGETS = {"kubernetes"}


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data or {}

    build_profile = data.get("build_profile") or {}
    architecture = build_profile.get("architecture", "monolith")
    deployment_target = build_profile.get("deployment_target", "docker_compose")

    if architecture not in _TRIGGER_ARCHITECTURES and deployment_target not in _TRIGGER_TARGETS:
        reason = f"architecture={architecture}, deployment_target={deployment_target}"
        logger.info("p17_control_plane: skipping — %s", reason)
        return TaskResult(
            output_path=str(output_dir),
            confidence=1.0,
            metadata={"skipped": True, "reason": reason},
            success=True,
        )

    domain_ir = data.get("domain_ir") or {}
    entities = domain_ir.get("entities") or []
    if not entities:
        entities = [{"table": "resource", "fields": [{"name": "name", "type": "string"}]}]

    project_name = data.get("project_name") or "app"
    slug = project_name.lower().replace(" ", "-")

    try:
        operator_dir = generate_operator_package(entities, slug, output_dir)
        logger.info("p17_control_plane: operator generated at %s", operator_dir)
        return TaskResult(
            output_path=str(operator_dir),
            confidence=0.9,
            metadata={"operator_dir": str(operator_dir), "entity_count": len(entities)},
            success=True,
        )
    except Exception as e:
        logger.error("p17_control_plane: generation failed: %s", e)
        return TaskResult(output_path=str(output_dir), confidence=0.0, metadata={}, success=False)
