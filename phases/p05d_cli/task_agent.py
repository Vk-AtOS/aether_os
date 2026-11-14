"""
P05d CLI — Command-line interface generation.

Activated when build_profile.build_type == "cli".
Generates a Click (Python) or Cobra (Go) CLI based on build_profile.backend_lang.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.phases.utils import get_domain_ir
from aether_os.phases.p05d_cli.cli_generator import generate_cli_project

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data or {}

    build_profile = data.get("build_profile") or {}
    build_type = build_profile.get("build_type", "web_app")

    if build_type != "cli":
        logger.info("p05d_cli: build_type=%s — skipping", build_type)
        return TaskResult(
            output_path=str(output_dir),
            confidence=1.0,
            metadata={"skipped": True, "reason": f"build_type={build_type}"},
            success=True,
        )

    domain_ir = get_domain_ir(data)
    entities = domain_ir.get("entities") or []
    if not entities:
        entities = [{"table": "item", "fields": [{"name": "name", "type": "string"}]}]

    project_name = data.get("project_name") or "CLI Tool"
    backend_lang = build_profile.get("backend_lang", "python")

    try:
        cli_dir = await generate_cli_project(entities, project_name, output_dir, backend_lang)
        return TaskResult(
            output_path=str(cli_dir),
            confidence=0.9,
            metadata={"cli_dir": str(cli_dir), "backend_lang": backend_lang, "entity_count": len(entities)},
            success=True,
        )
    except Exception as e:
        logger.error("p05d_cli: generation failed: %s", e)
        return TaskResult(output_path=str(output_dir), confidence=0.0, metadata={}, success=False)
