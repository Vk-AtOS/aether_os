"""
P18 Billing & Metering — OpenMeter + Stripe billing infrastructure generator.

Always runs — even if Stripe keys are not yet configured, the scaffolding
gives the generated project a ready-to-wire billing layer from day one.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.phases.utils import get_domain_ir
from aether_os.phases.p18_billing_metering.metering_generator import generate_billing_package

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data or {}

    domain_ir = get_domain_ir(data)
    entities = domain_ir.get("entities") or []
    if not entities:
        entities = [{"table": "resource", "fields": [{"name": "name", "type": "string"}]}]

    project_name = data.get("project_name") or "app"
    slug = project_name.lower().replace(" ", "-")

    try:
        billing_dir = generate_billing_package(entities, slug, output_dir)
        logger.info("p18_billing_metering: package generated at %s", billing_dir)
        return TaskResult(
            output_path=str(billing_dir),
            confidence=0.9,
            metadata={"billing_dir": str(billing_dir), "entity_count": len(entities)},
            success=True,
        )
    except Exception as e:
        logger.error("p18_billing_metering: generation failed: %s", e)
        return TaskResult(output_path=str(output_dir), confidence=0.0, metadata={}, success=False)
