"""
P16 IAM — OPA policy and Keycloak realm generation.

Always runs for cloud platform builds. Reads permission_model from p02c output
(falls back to empty dict which triggers sane defaults in iam_generator).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.phases.p16_iam.iam_generator import generate_iam_package

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data or {}

    permission_model: Dict = data.get("permission_model") or {}
    project_name: str = data.get("project_name") or "app"
    slug = project_name.lower().replace(" ", "-")

    try:
        iam_dir = generate_iam_package(permission_model, slug, output_dir)
        roles = list(permission_model.get("roles") or ["admin", "user", "viewer"])
        logger.info("p16_iam: IAM package generated at %s (roles=%s)", iam_dir, roles)
        return TaskResult(
            output_path=str(iam_dir),
            confidence=0.90,
            metadata={
                "iam_dir": str(iam_dir),
                "roles": roles,
                "has_permission_model": bool(permission_model),
            },
            success=True,
        )
    except Exception as e:
        logger.error("p16_iam: generation failed: %s", e)
        return TaskResult(output_path=str(output_dir), confidence=0.0, metadata={}, success=False)
