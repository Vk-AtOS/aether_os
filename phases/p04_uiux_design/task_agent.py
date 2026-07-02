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

    from aether_os.phases.utils import memory_hint
    mem = memory_hint(memory_ctx)

    # Extract designer_spec tokens if provided
    designer_spec = data.get("designer_spec", {})
    design_tokens = data.get("design_tokens", {})
    ds = (designer_spec.get("design", {}) if designer_spec else {}) or {}
    primary_hex = ds.get("primary_hex") or design_tokens.get("primary", "#6366f1")
    secondary_hex = ds.get("secondary_hex") or design_tokens.get("secondary", "#8b5cf6")
    bg_hex = ds.get("background_hex") or design_tokens.get("background", "#0f172a")
    surface_hex = ds.get("surface_hex") or design_tokens.get("accent", "#1e293b")
    font_pairing = ds.get("font_pairing", "Inter + Inter (system)")
    border_radius = ds.get("border_radius", "Rounded (8px)")
    layout = ds.get("layout", "sidebar-topbar")
    density = ds.get("density", "Normal")
    fe_spec = designer_spec.get("frontend", {}) if designer_spec else {}
    framework = fe_spec.get("framework", "React + Vite")
    styling = fe_spec.get("styling", "Tailwind CSS")

    FRONTEND_QUALITY_REQUIREMENTS = (
        "You are generating production-grade frontend code. Non-negotiable requirements: "
        "(1) Use only the framework and component library specified in the PROJECT SPECIFICATION above. "
        "(2) Every page must be fully responsive — mobile breakpoint at 640px, tablet at 768px. "
        "(3) All interactive elements must have keyboard focus states and ARIA labels. "
        "(4) Use the exact hex color values from the Design Tokens above as CSS custom properties: "
        "--color-primary, --color-secondary, --color-bg, --color-surface. "
        "(5) Every list view must include pagination — limit/offset with max 50 per page. "
        "(6) Every form must have inline validation with field-level error messages, not page-level alerts. "
        "(7) Include loading skeleton states for all async data. "
        "(8) Include empty state components for all list views. "
        "(9) Generate a /components directory with reusable components extracted from page code — "
        "do not inline everything in the page file. "
        "(10) Every page must have a corresponding test file in /tests/frontend/ with at minimum "
        "a render test and one interaction test."
    )

    design_spec: dict = {}
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        prompt = (
            f"You are a UI/UX designer. Generate a concise component design specification "
            f"for a {domain} SaaS app called '{project_name}'.\n\n"
            f"Framework: {framework}\nStyling: {styling}\n"
            f"Entities: {json.dumps([e.get('name') for e in entities[:8]])}\n\n"
            + mem +
            f"\n{FRONTEND_QUALITY_REQUIREMENTS}\n\n"
            "Return JSON:\n"
            '{"color_scheme": {"primary": "' + primary_hex + '", "secondary": "' + secondary_hex + '", '
            '"accent": "' + secondary_hex + '", "background": "' + bg_hex + '", "surface": "' + surface_hex + '"}, '
            '"typography": {"heading": "' + font_pairing.split(' + ')[0] + '", '
            '"body": "' + (font_pairing.split(' + ')[1] if ' + ' in font_pairing else 'Inter') + '"}, '
            '"border_radius": "' + border_radius + '", '
            '"density": "' + density + '", '
            '"layout": "' + layout + '", '
            '"css_custom_properties": {"--color-primary": "' + primary_hex + '", "--color-secondary": "' + secondary_hex + '", "--color-bg": "' + bg_hex + '", "--color-surface": "' + surface_hex + '"}, '
            '"components": [{"name": "ComponentName", "description": "what it does", "props": ["prop1", "prop2"]}], '
            '"pages": [{"name": "PageName", "route": "/route", "components": ["Component1"], '
            '"has_pagination": true, "has_skeleton": true, "has_empty_state": true, "test_file": "/tests/frontend/PageName.test.tsx"}], '
            '"quality_requirements": ' + json.dumps(FRONTEND_QUALITY_REQUIREMENTS[:200]) + '}'
        )
        design_spec = await llm.call_json(prompt, task_type="analysis")
        logger.info("[p04b] design spec generated for %s", project_name)
    except Exception as exc:
        logger.warning("[p04b] LLM design spec failed: %s", exc)
        design_spec = {
            "color_scheme": {"primary": primary_hex, "secondary": secondary_hex, "accent": secondary_hex, "background": bg_hex, "surface": surface_hex},
            "css_custom_properties": {"--color-primary": primary_hex, "--color-secondary": secondary_hex, "--color-bg": bg_hex, "--color-surface": surface_hex},
            "typography": {"heading": font_pairing.split(" + ")[0], "body": font_pairing.split(" + ")[1] if " + " in font_pairing else "Inter"},
            "border_radius": border_radius,
            "density": density,
            "layout": layout,
            "pages": [
                {"name": "Dashboard", "route": "/", "components": ["StatsCard", "DataTable"], "has_pagination": True, "has_skeleton": True, "has_empty_state": True, "test_file": "/tests/frontend/Dashboard.test.tsx"},
                {"name": "Settings", "route": "/settings", "components": ["SettingsForm"], "has_skeleton": True, "test_file": "/tests/frontend/Settings.test.tsx"},
            ],
        }

    spec_path = output_dir / "design_spec.json"
    spec_path.write_text(json.dumps(design_spec, indent=2, default=str))

    # Propagate design tokens and spec to downstream phases
    if design_spec.get("color_scheme"):
        phase_input.input_data["design_tokens"] = design_spec.get("color_scheme", {})
    if design_spec.get("css_custom_properties"):
        phase_input.input_data["css_custom_properties"] = design_spec["css_custom_properties"]
    if design_spec.get("pages"):
        phase_input.input_data["ui_pages"] = design_spec.get("pages", [])
    if designer_spec:
        phase_input.input_data["designer_spec"] = designer_spec

    return TaskResult(
        output_path=str(spec_path),
        confidence=0.80,
        metadata={"design_spec": design_spec, "project_name": project_name},
        success=True,
        issues=[],
    )
