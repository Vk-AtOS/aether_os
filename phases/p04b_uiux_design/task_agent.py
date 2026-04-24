"""P04b Task Agent — generate UI/UX design spec with Claude."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    requirements = data.get("requirements_doc", data.get("structured_requirements", ""))
    arch = data.get("architecture_json", {})
    if isinstance(arch, str):
        try:
            arch = json.loads(arch)
        except Exception:
            arch = {}
    llm = get_llm_client()

    # Generate DesignSpec
    design_prompt = (
        f"Create a complete UI/UX Design Spec for this software:\n\n"
        f"Requirements: {requirements[:2000]}\n"
        f"Tech stack: {arch.get('tech_stack', {})}\n\n"
        f"Return JSON with:\n"
        f"user_personas (list of {{name, role, goals, pain_points}}),\n"
        f"user_journeys (list of {{name, steps: list}}),\n"
        f"pages (list of {{name, purpose, components: list, layout_notes}}), min 3 pages,\n"
        f"design_tokens ({{colors: {{primary,secondary,error,success}}, "
        f"typography: {{font_family,sizes}}, spacing: {{unit,scale}}, "
        f"breakpoints: {{mobile,tablet,desktop}}}}),\n"
        f"component_inventory (list of component names, min 5),\n"
        f"accessibility_requirements (list, WCAG 2.1 AA minimum)"
    )
    spec = await llm.call_json(design_prompt, task_type="requirements")

    # Defaults
    spec.setdefault("user_personas", [{"name": "End User", "role": "user",
                                        "goals": ["complete tasks efficiently"],
                                        "pain_points": ["slow UI"]}])
    spec.setdefault("user_journeys", [{"name": "Main Flow", "steps": ["Login", "Dashboard", "Complete task"]}])
    spec.setdefault("pages", [{"name": "Home", "purpose": "Landing", "components": ["Header", "Hero", "Footer"], "layout_notes": "Full-width"},
                               {"name": "Dashboard", "purpose": "Main app view", "components": ["Sidebar", "DataTable", "Stats"], "layout_notes": "Sidebar layout"},
                               {"name": "Login", "purpose": "Auth", "components": ["LoginForm"], "layout_notes": "Centered"}])
    tokens = spec.get("design_tokens", {})
    tokens.setdefault("colors", {"primary": "#6366f1", "secondary": "#8b5cf6", "error": "#ef4444", "success": "#22c55e"})
    tokens.setdefault("typography", {"font_family": "Inter, sans-serif", "sizes": {"sm": "14px", "md": "16px", "lg": "20px", "xl": "24px"}})
    tokens.setdefault("spacing", {"unit": "4px", "scale": [0, 4, 8, 16, 24, 32, 48, 64]})
    tokens.setdefault("breakpoints", {"mobile": "640px", "tablet": "768px", "desktop": "1024px"})
    spec["design_tokens"] = tokens
    spec.setdefault("component_inventory", ["Button", "Input", "Card", "Modal", "Table", "Sidebar", "Header", "Footer"])
    spec.setdefault("accessibility_requirements", ["WCAG 2.1 AA compliance", "Keyboard navigation", "Screen reader support", "Min 4.5:1 colour contrast", "Focus indicators"])

    # Write files
    spec_path = output_dir / "design_spec.md"
    json_path = output_dir / "components.json"
    flows_path = output_dir / "user_flows.md"

    spec_path.write_text(_render_spec_md(spec))
    json_path.write_text(json.dumps({"components": spec["component_inventory"],
                                      "pages": spec.get("pages", []),
                                      "design_tokens": spec.get("design_tokens", {})}, indent=2))

    flows_md = ["# User Flows\n"]
    for journey in spec.get("user_journeys", []):
        flows_md.append(f"\n## {journey.get('name','Flow')}\n\n```mermaid\nflowchart TD")
        steps = journey.get("steps", [])
        for i, step in enumerate(steps):
            if i < len(steps) - 1:
                flows_md.append(f"  S{i}[\"{step}\"] --> S{i+1}[\"{steps[i+1]}\"]")
        flows_md.append("```\n")
    flows_path.write_text("\n".join(flows_md))

    issues = []
    if len(spec.get("pages", [])) < 1:
        issues.append("pages list is empty")
    if not all(k in tokens for k in ["colors", "typography", "spacing", "breakpoints"]):
        issues.append("design_tokens missing keys")
    if len(spec.get("component_inventory", [])) < 5:
        issues.append(f"component_inventory has {len(spec.get('component_inventory',[]))} items, need >= 5")

    return TaskResult(
        output_path=str(spec_path),
        confidence=0.85 if not issues else 0.5,
        metadata={"json_path": str(json_path), "flows_path": str(flows_path),
                  "component_count": len(spec.get("component_inventory", []))},
        issues=issues,
        success=len(issues) == 0,
    )


def _render_spec_md(spec: dict) -> str:
    lines = ["# UI/UX Design Specification\n"]
    lines.append("## User Personas\n")
    for p in spec.get("user_personas", []):
        lines.append(f"### {p.get('name','User')} — {p.get('role','')}")
        lines.append(f"**Goals:** {', '.join(p.get('goals',[]))}")
        lines.append(f"**Pain Points:** {', '.join(p.get('pain_points',[]))}\n")
    lines.append("## Pages\n")
    for pg in spec.get("pages", []):
        lines.append(f"### {pg.get('name','')}")
        lines.append(f"**Purpose:** {pg.get('purpose','')}")
        lines.append(f"**Components:** {', '.join(pg.get('components',[]))}")
        lines.append(f"**Layout:** {pg.get('layout_notes','')}\n")
    lines.append("## Component Inventory\n")
    for c in spec.get("component_inventory", []):
        lines.append(f"- {c}")
    lines.append("\n## Accessibility Requirements\n")
    for a in spec.get("accessibility_requirements", []):
        lines.append(f"- {a}")
    return "\n".join(lines)
