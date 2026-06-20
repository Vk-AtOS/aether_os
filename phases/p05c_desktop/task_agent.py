"""
P05c Desktop — Electron desktop app generation.

Activated when build_profile.frontend_framework == "electron".
Generates a complete Electron + React app that embeds the FastAPI backend
as a managed child process launched from the Electron main process.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.phases.p05c_desktop.electron_generator import generate_desktop_project

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data or {}

    build_profile = data.get("build_profile") or {}
    frontend_fw = build_profile.get("frontend_framework", "react")

    if frontend_fw != "electron":
        logger.info("p05c_desktop: frontend_framework=%s — skipping", frontend_fw)
        return TaskResult(
            output_path=str(output_dir),
            confidence=1.0,
            metadata={"skipped": True, "reason": f"frontend_framework={frontend_fw}"},
            success=True,
        )

    domain_ir = data.get("domain_ir") or {}
    entities = domain_ir.get("entities") or []
    if not entities:
        entities = [{"table": "item", "fields": [{"name": "name", "type": "string"}]}]

    project_name = data.get("project_name") or "Desktop App"
    api_port = 8000

    try:
        desktop_dir = await generate_desktop_project(entities, project_name, output_dir, api_port)
        logger.info("p05c_desktop: Electron app generated at %s", desktop_dir)
        return TaskResult(
            output_path=str(desktop_dir),
            confidence=0.85,
            metadata={"desktop_dir": str(desktop_dir), "entity_count": len(entities)},
            success=True,
        )
    except Exception as e:
        logger.error("p05c_desktop: generation failed: %s", e)
        return TaskResult(output_path=str(output_dir), confidence=0.0, metadata={}, success=False)
