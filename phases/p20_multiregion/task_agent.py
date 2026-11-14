"""P20 Multi-Region — task agent.

Activated when:
  build_profile.deployment_target == "kubernetes"
  AND build_profile.architecture in ("microservices", "event_driven")

Generates:
  chaos/          — LitmusChaos experiment manifests + test plan
  capacity/       — HPA + KEDA + PDB + ResourceQuota configs
  multiregion/    — Global Accelerator + Route53 + VPC peering Terraform
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.phases.utils import get_domain_ir
from aether_os.core.chaos_engineering.chaos_generator import generate_chaos_package
from aether_os.core.capacity_planner.planner import generate_capacity_package
from aether_os.phases.p20_multiregion.multiregion_generator import generate_multiregion_package

logger = logging.getLogger(__name__)

_ELIGIBLE_ARCHITECTURES = {"microservices", "event_driven"}


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """Generate multi-region + chaos + capacity packages."""
    output_dir.mkdir(parents=True, exist_ok=True)
    data: dict = getattr(phase_input, "input_data", {}) or {}

    build_profile: dict = data.get("build_profile") or {}
    deployment_target = build_profile.get("deployment_target", "")
    architecture = build_profile.get("architecture", "")

    if deployment_target != "kubernetes" or architecture not in _ELIGIBLE_ARCHITECTURES:
        logger.info(
            "p20_multiregion: skipping (deployment_target=%s, architecture=%s)",
            deployment_target,
            architecture,
        )
        return TaskResult(
            output_path=str(output_dir),
            confidence=1.0,
            metadata={"skipped": True, "reason": f"deployment_target={deployment_target}, architecture={architecture}"},
            success=True,
        )

    project_name: str = data.get("project_name", "app")
    slug = re.sub(r"[^a-z0-9-]", "-", project_name.lower()).strip("-") or "app"

    domain_ir: dict = get_domain_ir(data)
    entities: List[dict] = domain_ir.get("entities") or []
    if not entities:
        entities = [{"table": "item", "fields": [{"name": "name", "type": "string"}]}]

    performance_tier: str = build_profile.get("performance_tier", "standard")
    message_queue: str = build_profile.get("message_queue", "")

    files_written: List[str] = []

    try:
        chaos_dir = generate_chaos_package(entities, slug, output_dir)
        files_written.append(str(chaos_dir.relative_to(output_dir)))
        logger.info("p20_multiregion: chaos package written to %s", chaos_dir)
    except Exception as e:
        logger.warning("p20_multiregion: chaos package failed: %s", e)

    try:
        capacity_dir = generate_capacity_package(entities, slug, output_dir, performance_tier, message_queue)
        files_written.append(str(capacity_dir.relative_to(output_dir)))
        logger.info("p20_multiregion: capacity package written to %s", capacity_dir)
    except Exception as e:
        logger.warning("p20_multiregion: capacity package failed: %s", e)

    try:
        mr_dir = generate_multiregion_package(entities, slug, output_dir)
        files_written.append(str(mr_dir.relative_to(output_dir)))
        logger.info("p20_multiregion: multiregion package written to %s", mr_dir)
    except Exception as e:
        logger.warning("p20_multiregion: multiregion package failed: %s", e)

    return TaskResult(
        output_path=str(output_dir),
        confidence=0.9,
        metadata={
            "phase": "p20_multiregion",
            "project_name": project_name,
            "slug": slug,
            "entity_count": len(entities),
            "performance_tier": performance_tier,
            "files_written": files_written,
        },
        success=bool(files_written),
    )
