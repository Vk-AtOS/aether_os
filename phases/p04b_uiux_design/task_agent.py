"""P04b UI/UX Design — generates component spec and design tokens for the frontend."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    project_name: str = data.get("project_name", "App")
    domain: str = data.get("domain", "general")
    entities: list = data.get("entities", [])

    design_spec: dict = {}
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        prompt = (
            f"You are a UI/UX designer. Generate a concise component design specification "
            f"for a {domain} SaaS app called '{project_name}'.\n\n"
            f"Entities: {json.dumps([e.get('name') for e in entities[:8]])}\n\n"
            "Return JSON:\n"
            '{"color_scheme": {"primary": "#hex", "secondary": "#hex", "accent": "#hex", "background": "#hex"}, '
            '"typography": {"heading": "font-name", "body": "font-name"}, '
            '"components": [{"name": "ComponentName", "description": "what it does", "props": ["prop1", "prop2"]}], '
            '"pages": [{"name": "PageName", "route": "/route", "components": ["Component1"]}], '
            '"layout": "sidebar|top-nav|minimal"}'
        )
        design_spec = await llm.call_json(prompt, task_type="analysis")
        logger.info("[p04b] design spec generated for %s", project_name)
    except Exception as exc:
        logger.warning("[p04b] LLM design spec failed: %s", exc)
        design_spec = {
            "color_scheme": {"primary": "#6366f1", "secondary": "#8b5cf6", "accent": "#f59e0b", "background": "#0f172a"},
            "typography": {"heading": "Inter", "body": "Inter"},
            "layout": "sidebar",
            "pages": [
                {"name": "Dashboard", "route": "/", "components": ["StatsCard", "DataTable"]},
                {"name": "Settings", "route": "/settings", "components": ["SettingsForm"]},
            ],
        }

    spec_path = output_dir / "design_spec.json"
    spec_path.write_text(json.dumps(design_spec, indent=2, default=str))

    # Propagate design tokens to downstream phases
    if design_spec.get("color_scheme"):
        phase_input.input_data["design_tokens"] = design_spec.get("color_scheme", {})
    if design_spec.get("pages"):
        phase_input.input_data["ui_pages"] = design_spec.get("pages", [])

    return TaskResult(
        output_path=str(spec_path),
        confidence=0.80,
        metadata={"design_spec": design_spec, "project_name": project_name},
        success=True,
        issues=[],
    )
