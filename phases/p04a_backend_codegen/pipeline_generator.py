"""
P04a Pipeline Generator — generates service stubs and orchestrators from
BusinessProcessPipeline definitions stored in domain knowledge packs.

Output (written into the generated project's src/ directory):
  src/services/{service}.py            — one class per unique service_required
  src/services/pipelines/__init__.py   — package marker
  src/services/pipelines/{pipeline}_orchestrator.py — step sequencer per pipeline
  src/routers/pipeline_events.py       — FastAPI endpoints that trigger orchestrators
  src/PIPELINES.md                     — human-readable documentation
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)


# ── Template helpers ───────────────────────────────────────────────────────────

def _to_snake(name: str) -> str:
    """PascalCase or camelCase → snake_case."""
    import re
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


def _collect_services(pipelines: list) -> Dict[str, List[Tuple[str, str, str]]]:
    """
    Walk all pipelines and collect unique services with their methods.

    Returns: {ServiceName: [(method, description, input_keys_str), ...]}
    The same (service, method) pair is deduplicated across pipelines.
    """
    services: Dict[str, Dict[str, Tuple[str, str]]] = {}
    for pipeline in pipelines:
        for step in pipeline.steps:
            svc = step.service_required
            method = step.method
            if svc not in services:
                services[svc] = {}
            if method not in services[svc]:
                keys_str = ", ".join(step.input_keys) if step.input_keys else "none"
                services[svc][method] = (step.description, keys_str)
    # Flatten: {ServiceName: [(method, description, keys_str), ...]}
    return {
        svc: [(m, desc, keys) for m, (desc, keys) in methods.items()]
        for svc, methods in services.items()
    }


def _service_stub(service_name: str, methods: List[Tuple[str, str, str]]) -> str:
    """Render a service stub file for one service."""
    lines = [
        f'"""',
        f"{service_name} — generated service stub from AetherOS BusinessProcessPipeline.",
        "Replace stub implementations with real business logic.",
        '"""',
        "from __future__ import annotations",
        "import logging",
        "from typing import Any, Dict",
        "",
        "logger = logging.getLogger(__name__)",
        "",
        "",
        f"class {service_name}:",
        f'    """Service stub for {service_name}. Implement the methods below."""',
        "",
    ]
    for method, description, keys_str in methods:
        lines += [
            f"    async def {method}(self, payload: Dict[str, Any]) -> Dict[str, Any]:",
            f'        """',
            f"        {description}",
            f"        Input keys: {keys_str}",
            '        Returns: {"success": bool, "result": any, "error": str | None}',
            '        """',
            f'        logger.info("{service_name}.{method} called with payload=%s", payload)',
            f"        # TODO: Implement {method}",
            '        return {"success": True, "result": None, "error": None}',
            "",
        ]
    return "\n".join(lines)


def _orchestrator(pipeline: Any) -> str:
    """Render the orchestrator class for one BusinessProcessPipeline."""
    name = pipeline.name
    steps = pipeline.steps

    # Collect unique services used by this pipeline (preserving first-seen order)
    seen: Set[str] = set()
    unique_services: List[str] = []
    for step in steps:
        svc = step.service_required
        if svc not in seen:
            seen.add(svc)
            unique_services.append(svc)

    step_list_lines = "\n".join(
        f"  {i + 1}. {s.name} → {s.service_required}.{s.method}" for i, s in enumerate(steps)
    )
    integrations = ", ".join(pipeline.integrations_required) if pipeline.integrations_required else "none"

    # Build __init__ service injection block
    init_lines: List[str] = []
    for svc in unique_services:
        mod = _to_snake(svc)
        attr = _to_snake(svc)
        init_lines.append(f"        from services.{mod} import {svc}")
        init_lines.append(f"        self.{attr} = {svc}()")

    # Build run() step blocks
    run_lines: List[str] = []
    for i, step in enumerate(steps):
        svc_attr = _to_snake(step.service_required)
        run_lines += [
            f"        # Step {i + 1}: {step.name}",
            "        try:",
            f"            result = await self.{svc_attr}.{step.method}(context)",
            "            if not result.get(\"success\"):",
            f"                logger.warning(\"{name}: step {step.name} failed: %s\", result.get(\"error\"))",
            f"                return {{\"completed\": False, \"final_step\": \"{step.name}\", \"error\": result.get(\"error\")}}",
            f"            context[\"{step.name}\"] = result.get(\"result\")",
            "        except Exception as exc:",
            f"            logger.error(\"{name}: step {step.name} raised: %s\", exc)",
            f"            return {{\"completed\": False, \"final_step\": \"{step.name}\", \"error\": str(exc)}}",
            "",
        ]

    last_step_name = steps[-1].name if steps else "done"

    lines = [
        '"""',
        f"{name}Orchestrator — generated from AetherOS BusinessProcessPipeline.",
        "",
        f"Trigger: {pipeline.trigger} on {pipeline.trigger_entity} when {pipeline.trigger_condition}",
        f"Integrations required: {integrations}",
        "",
        "Step sequence:",
        step_list_lines,
        '"""',
        "from __future__ import annotations",
        "import logging",
        "from typing import Any, Dict",
        "",
        "logger = logging.getLogger(__name__)",
        "",
        "",
        f"class {name}Orchestrator:",
        f'    """',
        f"    Orchestrates the {name} business process.",
        "",
        "    Each step calls the appropriate service and routes to the next step",
        "    based on success/failure outcomes.",
        '    """',
        "",
        "    def __init__(self):",
        "        # Inject service dependencies",
        *init_lines,
        "",
        "    async def run(self, trigger_payload: Dict[str, Any]) -> Dict[str, Any]:",
        f'        """',
        f"        Execute the full {name} pipeline.",
        '        Returns: {"completed": bool, "final_step": str, "error": str | None}',
        '        """',
        "        context: Dict[str, Any] = {\"trigger\": trigger_payload}",
        "",
        *run_lines,
        f"        logger.info(\"{name} completed successfully\")",
        f"        return {{\"completed\": True, \"final_step\": \"{last_step_name}\", \"error\": None}}",
    ]
    return "\n".join(lines)


def _pipeline_events_router(pipelines: list) -> str:
    """Render the pipeline_events.py FastAPI router for all pipelines."""
    import_lines: List[str] = []
    route_lines: List[str] = []

    for pipeline in pipelines:
        name = pipeline.name
        mod = _to_snake(name)
        endpoint = _to_snake(name).replace("_flow", "").replace("_", "-")
        fn_name = _to_snake(name)

        import_lines.append(
            f"from services.pipelines.{mod}_orchestrator import {name}Orchestrator"
        )
        route_lines += [
            "",
            f"@router.post(\"/{endpoint}\", status_code=202)",
            f"async def trigger_{fn_name}(",
            "    payload: dict,",
            "    background_tasks: BackgroundTasks,",
            "    current_user: dict = Depends(get_current_user),",
            "):",
            f'    """',
            f"    Trigger {name}.",
            f"    Trigger condition: {pipeline.trigger_condition}",
            "    Runs the orchestrator in the background and returns 202 Accepted immediately.",
            '    """',
            f"    orchestrator = {name}Orchestrator()",
            "    background_tasks.add_task(orchestrator.run, payload)",
            f"    return {{\"status\": \"accepted\", \"pipeline\": \"{name}\"}}",
        ]

    lines = [
        '"""',
        "Pipeline event triggers — generated from AetherOS BusinessProcessPipeline definitions.",
        "",
        "These endpoints fire pipeline orchestrators when business events occur.",
        '"""',
        "from __future__ import annotations",
        "import logging",
        "from fastapi import APIRouter, BackgroundTasks, Depends",
        "from auth import get_current_user",
        *import_lines,
        "",
        "logger = logging.getLogger(__name__)",
        "router = APIRouter(prefix=\"/pipeline-events\", tags=[\"Pipeline Events\"])",
        *route_lines,
    ]
    return "\n".join(lines)


def _pipelines_md(pipelines: list, domain: str) -> str:
    """Render PIPELINES.md documentation for all pipelines."""
    lines = [
        "# Business Process Pipelines",
        "",
        f"Generated by AetherOS from domain knowledge pack: `{domain}`",
        "",
    ]
    for pipeline in pipelines:
        services_str = ", ".join({s.service_required for s in pipeline.steps})
        integrations_str = ", ".join(pipeline.integrations_required) if pipeline.integrations_required else "none"
        lines += [
            f"## {pipeline.name}",
            "",
            f"- **Trigger:** `{pipeline.trigger}` on `{pipeline.trigger_entity}` when `{pipeline.trigger_condition}`",
            f"- **Steps:** {len(pipeline.steps)} steps",
            f"- **Services:** {services_str}",
            f"- **Integrations:** {integrations_str}",
            "",
            "### Step Sequence",
            "",
            "| # | Step | Service | Method | On Failure |",
            "|---|------|---------|--------|------------|",
        ]
        for i, step in enumerate(pipeline.steps):
            lines.append(
                f"| {i + 1} | {step.name} | {step.service_required} | {step.method} | {step.on_failure} |"
            )
        lines += [
            "",
            "### To implement",
            "",
            f"Replace stub implementations in `src/services/{{service}}.py` with real business logic.",
            "",
        ]
    return "\n".join(lines)


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_pipeline_code(pipelines: list, output_src_dir: Path, domain: str = "general") -> List[str]:
    """
    Generate service stubs, orchestrators, event router, and documentation
    from a list of BusinessProcessPipeline objects.

    Args:
        pipelines:       List of BusinessProcessPipeline instances from the domain pack.
        output_src_dir:  Path to src/ in the generated project.
        domain:          Domain name string (for documentation only).

    Returns:
        List of absolute file paths written.
    """
    if not pipelines:
        logger.debug("pipeline_generator: no pipelines to generate")
        return []

    written: List[str] = []

    # Create services/ and services/pipelines/ directories
    svc_dir = output_src_dir / "services"
    pipelines_dir = svc_dir / "pipelines"
    svc_dir.mkdir(parents=True, exist_ok=True)
    pipelines_dir.mkdir(parents=True, exist_ok=True)

    # Write __init__.py markers (preserve existing if present)
    for init_path in (svc_dir / "__init__.py", pipelines_dir / "__init__.py"):
        if not init_path.exists():
            init_path.write_text("")
            written.append(str(init_path))

    # Collect all unique services across all pipelines
    services_map = _collect_services(pipelines)

    # Write one stub file per unique service
    for service_name, methods in services_map.items():
        file_path = svc_dir / f"{_to_snake(service_name)}.py"
        # Do not overwrite if a real implementation already exists
        if not file_path.exists():
            file_path.write_text(_service_stub(service_name, methods))
            written.append(str(file_path))
            logger.debug("pipeline_generator: wrote service stub %s", file_path)

    # Write one orchestrator file per pipeline
    for pipeline in pipelines:
        mod_name = _to_snake(pipeline.name)
        file_path = pipelines_dir / f"{mod_name}_orchestrator.py"
        file_path.write_text(_orchestrator(pipeline))
        written.append(str(file_path))
        logger.debug("pipeline_generator: wrote orchestrator %s", file_path)

    # Write the event-trigger router
    router_path = output_src_dir / "routers" / "pipeline_events.py"
    router_path.parent.mkdir(parents=True, exist_ok=True)
    router_path.write_text(_pipeline_events_router(pipelines))
    written.append(str(router_path))
    logger.debug("pipeline_generator: wrote event router %s", router_path)

    # Write human-readable documentation into src/PIPELINES.md
    doc_path = output_src_dir / "PIPELINES.md"
    doc_path.write_text(_pipelines_md(pipelines, domain))
    written.append(str(doc_path))

    logger.info(
        "pipeline_generator: generated %d files for %d pipelines, %d services",
        len(written), len(pipelines), len(services_map),
    )
    return written
