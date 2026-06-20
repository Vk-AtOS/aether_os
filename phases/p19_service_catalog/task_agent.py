"""
P19 Service Catalog Task Agent — AetherOS Layer 7.

Only runs when build_profile.build_type == "cloud_platform".
Generates:
  - service_catalog/ backend files (router.py, models.py, migration.sql)
  - frontend/ cloud management console (React + Vite)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.phases.p19_service_catalog.catalog_generator import generate_catalog_package
from aether_os.phases.p05_frontend.cloud_console_generator import generate_cloud_console

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data or {}

    build_profile = data.get("build_profile") or {}
    build_type = build_profile.get("build_type", "")

    if build_type != "cloud_platform":
        logger.info("p19_service_catalog: build_type=%s — skipping", build_type)
        return TaskResult(
            output_path=str(output_dir),
            confidence=1.0,
            metadata={"skipped": True, "reason": f"build_type={build_type}"},
            success=True,
        )

    domain_ir = data.get("domain_ir") or {}
    entities: List[Dict] = domain_ir.get("entities") or []
    if not entities:
        entities = [{"table": "resource", "name": "Resource", "columns": ["id", "name", "status"]}]

    project_name: str = data.get("project_name") or "Cloud Platform"
    slug: str = project_name.lower().replace(" ", "-")
    backend_lang: str = build_profile.get("backend_lang", "python")

    services: List[Dict] = data.get("services") or []

    try:
        catalog_dir = generate_catalog_package(entities, slug, output_dir, backend_lang)
        console_dir = await generate_cloud_console(entities, services, project_name, output_dir)

        router_file = catalog_dir / "router.py"
        file_count = sum(1 for f in catalog_dir.rglob("*") if f.is_file())
        file_count += sum(1 for f in console_dir.rglob("*") if f.is_file())

        logger.info("p19_service_catalog: generated %d files at %s", file_count, output_dir)
        return TaskResult(
            output_path=str(catalog_dir),
            confidence=0.9,
            metadata={
                "catalog_dir": str(catalog_dir),
                "console_dir": str(console_dir),
                "entity_count": len(entities),
                "service_count": len(services) or len(entities),
                "files_generated": file_count,
                "router_exists": router_file.exists(),
            },
            success=True,
        )
    except Exception as e:
        logger.error("p19_service_catalog: generation failed: %s", e)
        return TaskResult(output_path=str(output_dir), confidence=0.0, metadata={}, success=False)
