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
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)


# ── Template helpers ───────────────────────────────────────────────────────────

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _svc(step: Any) -> str:
    """Service class of a step. ProcessStep has been declared twice in core.domain_knowledge.base: the old shape
    named it service_required, the one that wins calls it service. Reading only the old name raised
    AttributeError and fintech/healthcare apps lost their pipelines (KAN-169)."""
    name = getattr(step, "service_required", None) or getattr(step, "service", None)
    if not name or not _IDENT.match(name):
        raise ValueError(f"pipeline step {getattr(step, 'name', '?')!r} has no usable service name")
    return name


def _keys(step: Any) -> List[str]:
    return list(getattr(step, "input_keys", None) or getattr(step, "input_mapping", None) or [])


def _text(value: Any) -> str:
    """Free text that goes into a docstring or comment: no quotes, backslashes or line breaks."""
    return re.sub(r'["\\\r\n]+', " ", str(value or "")).strip()


def _check_names(pipeline: Any) -> None:
    for ident in [pipeline.name] + [x for st in pipeline.steps for x in (st.name, st.method)]:
        if not _IDENT.match(str(ident)):
            raise ValueError(f"pipeline {pipeline.name!r}: {ident!r} is not a plain identifier")

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
            svc = _svc(step)
            method = step.method
            if svc not in services:
                services[svc] = {}
            if method not in services[svc]:
                keys_str = ", ".join(_keys(step)) or "none"
                services[svc][method] = (_text(step.description), keys_str)
    # Flatten: {ServiceName: [(method, description, keys_str), ...]}
    return {
        svc: [(m, desc, keys) for m, (desc, keys) in methods.items()]
        for svc, methods in services.items()
    }


def _service_stub(service_name: str, methods: List[Tuple[str, str, str]]) -> str:
    """Render a service stub file for one service."""
    lines = [
        '"""',
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
            '        """',
            f"        {_text(description)}",
            f"        Input keys: {keys_str}",
            '        Returns: {"success": bool, "result": any, "error": str | None}',
            '        """',
            f'        logger.info("{service_name}.{method} called with payload=%s", payload)',
            "        # Not implemented: a stub must never report success, or a pipeline looks completed when nothing ran.",
            f'        raise NotImplementedError("{service_name}.{method} is not implemented")',
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
        svc = _svc(step)
        if svc not in seen:
            seen.add(svc)
            unique_services.append(svc)

    step_list_lines = "\n".join(
        f"  {i + 1}. {s.name} → {_svc(s)}.{s.method}" for i, s in enumerate(steps)
    )
    integrations = ", ".join(_text(x) for x in pipeline.integrations_required) if pipeline.integrations_required else "none"

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
        svc_attr = _to_snake(_svc(step))
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
            f"            return {{\"completed\": False, \"final_step\": \"{step.name}\", \"error\": exc.__class__.__name__}}",
            "",
        ]

    last_step_name = steps[-1].name if steps else "done"

    lines = [
        '"""',
        f"{name}Orchestrator — generated from AetherOS BusinessProcessPipeline.",
        "",
        f"Trigger: {_text(pipeline.trigger)} on {_text(pipeline.trigger_entity)} when {_text(pipeline.trigger_condition)}",
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
        '    """',
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
        '        """',
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
            f"@router.post(\"/{endpoint}\")",
            f"async def trigger_{fn_name}(",
            "    payload: dict,",
            "    current_user: dict = Depends(require_role(\"admin\", \"member\")),",
            "):",
            '    """',
            f"    Trigger {name} (roles: admin, member).",
            f"    Trigger condition: {_text(pipeline.trigger_condition)}",
            "    Runs the steps in order and answers with the outcome: 200 when every step succeeded, 501 when a step",
            "    is still a stub, 502 when a step failed. It never reports success for work that did not run.",
            '    """',
            f"    orchestrator = {name}Orchestrator()",
            "    result = await orchestrator.run({**payload, \"_caller\": {\"id\": current_user.get(\"id\"), \"org_id\": current_user.get(\"org_id\")}})",
            "    if not result.get(\"completed\"):",
            "        logger.warning(\"pipeline %s stopped at %s: %s\", " + repr(name) + ", result.get(\"final_step\"), result.get(\"error\"))",
            "        code = 501 if result.get(\"error\") == \"NotImplementedError\" else 502",
            "        raise HTTPException(status_code=code, detail=f\"Pipeline step {result.get('final_step')} did not complete\")",
            f"    return {{\"status\": \"completed\", \"pipeline\": \"{name}\"}}",
        ]

    lines = [
        '"""',
        "Pipeline event triggers — generated from AetherOS BusinessProcessPipeline definitions.",
        "",
        "These endpoints fire pipeline orchestrators when business events occur.",
        '"""',
        "from __future__ import annotations",
        "import logging",
        "from fastapi import APIRouter, Depends, HTTPException",
        "from auth import require_role",
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
        services_str = ", ".join(sorted({_svc(s) for s in pipeline.steps}))
        integrations_str = ", ".join(pipeline.integrations_required) if pipeline.integrations_required else "none"
        lines += [
            f"## {pipeline.name}",
            "",
            f"- **Trigger:** `{_text(pipeline.trigger)}` on `{_text(pipeline.trigger_entity)}` when `{_text(pipeline.trigger_condition)}`",
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
                f"| {i + 1} | {step.name} | {_svc(step)} | {step.method} | {_text(step.on_failure)} |"
            )
        lines += [
            "",
            "### To implement",
            "",
            "Replace stub implementations in `src/services/{service}.py` with real business logic.",
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

    for pipeline in pipelines:
        _check_names(pipeline)
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
