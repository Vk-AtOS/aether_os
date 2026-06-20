"""
P05e Serverless — Knative function scaffolding generation.

Activated when build_profile.architecture in ("serverless", "event_driven").
Generates Knative Service manifests, Broker+Trigger YAML, and function handlers
for each domain entity.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.phases.p05e_serverless.serverless_generator import generate_serverless_package

logger = logging.getLogger(__name__)

_SERVERLESS_ARCHITECTURES = {"serverless", "event_driven"}


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data or {}

    build_profile = data.get("build_profile") or {}
    architecture = build_profile.get("architecture", "monolith")

    if architecture not in _SERVERLESS_ARCHITECTURES:
        logger.info("p05e_serverless: architecture=%s — skipping", architecture)
        return TaskResult(
            output_path=str(output_dir),
            confidence=1.0,
            metadata={"skipped": True, "reason": f"architecture={architecture}"},
            success=True,
        )

    domain_ir = data.get("domain_ir") or {}
    entities = domain_ir.get("entities") or []
    if not entities:
        entities = [{"table": "item", "fields": [{"name": "name", "type": "string"}]}]

    project_name = data.get("project_name") or "app"
    slug = project_name.lower().replace(" ", "-")
    backend_lang = build_profile.get("backend_language", "python")

    try:
        serverless_dir = generate_serverless_package(entities, slug, output_dir, backend_lang)
        fn_count = len(entities) * 3  # created/updated/deleted per entity
        logger.info("p05e_serverless: generated %d functions at %s", fn_count, serverless_dir)
        return TaskResult(
            output_path=str(serverless_dir),
            confidence=0.85,
            metadata={
                "serverless_dir": str(serverless_dir),
                "function_count": fn_count,
                "entity_count": len(entities),
                "backend_lang": backend_lang,
            },
            success=True,
        )
    except Exception as e:
        logger.error("p05e_serverless: generation failed: %s", e)
        return TaskResult(output_path=str(output_dir), confidence=0.0, metadata={}, success=False)
