"""P04c Task Agent — generate frontend code with Claude (OpenHands optional)."""
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
    design_spec_path = data.get("design_spec_path", "")
    components_json_path = data.get("components_json_path", "")
    arch_json = data.get("architecture_json", {})
    if isinstance(arch_json, str):
        try:
            arch_json = json.loads(arch_json)
        except Exception:
            arch_json = {}

    design_spec = ""
    components = {}
    if design_spec_path and Path(design_spec_path).exists():
        design_spec = Path(design_spec_path).read_text()
    if components_json_path and Path(components_json_path).exists():
        components = json.loads(Path(components_json_path).read_text())

    frontend_stack = arch_json.get("tech_stack", {}).get("frontend", "vanilla-js")
    api_base = data.get("api_base_url", "http://localhost:8000")
    llm = get_llm_client()
    frontend_dir = output_dir / "frontend"
    frontend_dir.mkdir(parents=True, exist_ok=True)

    # Try OpenHands first
    files_written = []
    try:
        import openhands
        from openhands.core.main import run_controller
        instruction = (
            f"Build a {frontend_stack} frontend at {frontend_dir} based on:\n"
            f"Design spec:\n{design_spec[:2000]}\nAPI base URL: {api_base}\n"
            f"Implement all pages and components listed. Include loading, error, empty states."
        )
        await run_controller(task=instruction, workspace_base=str(frontend_dir))
        files_written = [str(f) for f in frontend_dir.rglob("*") if f.is_file()]
    except Exception as e:
        logger.info("OpenHands unavailable: %s — using direct LLM", e)
        files_written = await _generate_with_llm(
            frontend_dir, design_spec, components, arch_json, api_base, llm)

    # Validate files exist for all pages
    pages = components.get("pages", [])
    issues = []
    all_files = [f.name for f in frontend_dir.rglob("*") if f.is_file()]
    for page in pages:
        page_name = page.get("name", "").lower().replace(" ", "_")
        if not any(page_name in f.lower() for f in all_files):
            issues.append(f"Page '{page.get('name')}' has no corresponding file")

    component_list = components.get("components", [])
    for comp in component_list:
        comp_name = comp.lower().replace(" ", "_")
        if not any(comp_name in f.lower() for f in all_files):
            issues.append(f"Component '{comp}' not found in generated files")

    # Cap issues at 5 for readability
    issues = issues[:5]
    return TaskResult(
        output_path=str(frontend_dir),
        confidence=0.8 if not issues else 0.5,
        metadata={"files_written": len(files_written), "frontend_stack": frontend_stack},
        issues=issues,
        success=len(issues) == 0,
    )


async def _generate_with_llm(frontend_dir: Path, design_spec: str, components: dict,
                               arch: dict, api_base: str, llm) -> List[str]:
    pages = components.get("pages", [{"name": "index", "components": []}])
    comp_list = components.get("components", ["Button", "Card", "Header"])
    tokens = components.get("design_tokens", {})
    colors = tokens.get("colors", {"primary": "#6366f1"})
    files = []

    # Generate CSS with design tokens
    css_code = await llm.call(
        f"Generate a CSS file with these design tokens: {json.dumps(tokens)}. "
        f"Include: CSS custom properties, base reset, utility classes for layout, "
        f"button styles, form styles, card styles.",
        task_type="code_generation",
    )
    css_path = frontend_dir / "styles.css"
    css_path.write_text(_strip_fences(css_code))
    files.append(str(css_path))

    # Generate component files
    for comp in comp_list[:8]:
        comp_code = await llm.call(
            f"Write a vanilla JavaScript component for '{comp}'.\n"
            f"API base: {api_base}\nDesign tokens: {json.dumps(colors)}\n"
            f"Return a JS class/function that renders HTML and handles state.",
            task_type="code_generation",
        )
        comp_file = frontend_dir / f"{comp.lower().replace(' ','_')}.js"
        comp_file.write_text(_strip_fences(comp_code))
        files.append(str(comp_file))

    # Generate page HTML files
    for page in pages[:5]:
        page_name = page.get("name", "index").lower().replace(" ", "_")
        page_comps = page.get("components", [])
        page_code = await llm.call(
            f"Write an HTML page for '{page.get('name')}' with purpose: {page.get('purpose','')}\n"
            f"Include components: {', '.join(page_comps)}\n"
            f"Link to styles.css. Load JS components. API base: {api_base}\n"
            f"Include loading states, error states, empty states. "
            f"Use {colors.get('primary','#6366f1')} as primary colour.",
            task_type="code_generation",
        )
        page_file = frontend_dir / f"{page_name}.html"
        page_file.write_text(_strip_fences(page_code))
        files.append(str(page_file))

    return files


def _strip_fences(code: str) -> str:
    lines = code.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
