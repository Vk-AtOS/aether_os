"""P15 Task Agent — handle change requests with partial pipeline re-execution."""
from __future__ import annotations
import json, logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client
logger = logging.getLogger(__name__)

AREA_TO_PHASES = {
    "requirements": ["p01_requirements","p02_architecture","p03_scaffolding",
                     "p04a_backend_codegen","p04b_uiux_design","p04c_frontend_codegen",
                     "p04d_component_library","p04e_integration","p05_code_review",
                     "p06_security","p07a_unit_testing","p07b_performance_testing",
                     "p07c_accessibility_testing","p07d_e2e_testing","p08_cicd",
                     "p09_documentation","p10_deployment","p11a_monitoring",
                     "p11b_error_tracking","p11c_analytics","p11d_alerting",
                     "p12a_feature_flags","p12b_ab_testing","p13_app_memory","p14_client_portal"],
    "architecture": ["p02_architecture","p03_scaffolding","p04a_backend_codegen",
                     "p04b_uiux_design","p04c_frontend_codegen","p09_documentation","p10_deployment"],
    "backend code": ["p04a_backend_codegen","p05_code_review","p06_security",
                     "p07a_unit_testing","p08_cicd"],
    "frontend":     ["p04b_uiux_design","p04c_frontend_codegen","p04d_component_library",
                     "p04e_integration","p07c_accessibility_testing","p07d_e2e_testing"],
    "design":       ["p04b_uiux_design","p04c_frontend_codegen","p04d_component_library","p04e_integration"],
    "deployment":   ["p10_deployment","p11a_monitoring","p11b_error_tracking",
                     "p11c_analytics","p11d_alerting"],
}


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    project_id = phase_input.project_id
    change_description = data.get("change_description", data.get("raw_text", ""))
    affected_areas = data.get("affected_areas", [])
    llm = get_llm_client()

    # If no affected areas specified, infer from description
    if not affected_areas and change_description:
        inferred = await llm.call_json(
            f"Given this change request, which areas are affected?\n"
            f"Change: {change_description}\n\n"
            f"Available areas: {list(AREA_TO_PHASES.keys())}\n"
            f"Return JSON: {{\"affected_areas\": [list of area names]}}",
            task_type="requirements",
        )
        affected_areas = inferred.get("affected_areas", ["backend code"])

    # Determine phases to re-run
    phases_to_run = set()
    for area in affected_areas:
        area_lower = area.lower()
        for key, phases in AREA_TO_PHASES.items():
            if key in area_lower or area_lower in key:
                phases_to_run.update(phases)
                break
    if not phases_to_run:
        phases_to_run = set(AREA_TO_PHASES.get("backend code", []))

    phases_ordered = [p for p in [
        "p01_requirements","p02_architecture","p03_scaffolding","p04a_backend_codegen",
        "p04b_uiux_design","p04c_frontend_codegen","p04d_component_library","p04e_integration",
        "p05_code_review","p06_security","p07a_unit_testing","p07b_performance_testing",
        "p07c_accessibility_testing","p07d_e2e_testing","p08_cicd","p09_documentation",
        "p10_deployment","p11a_monitoring","p11b_error_tracking","p11c_analytics",
        "p11d_alerting","p12a_feature_flags","p12b_ab_testing","p13_app_memory","p14_client_portal"
    ] if p in phases_to_run]

    estimate_mins = len(phases_ordered) * 3

    # Post to orchestrator bus to trigger partial re-run
    try:
        from aether_os.orchestrator.bus import get_bus
        from aether_os.orchestrator.messages import PhaseMessage, PhaseResult
        msg = PhaseMessage(
            from_phase="p15_change_requests",
            to_phase=phases_ordered[0] if phases_ordered else None,
            result=PhaseResult(
                run_id=phase_input.run_id,
                phase="p15_change_requests",
                status="passed",
                output_path=str(output_dir),
                confidence=0.9,
                next_phase=phases_ordered[0] if phases_ordered else None,
                artifacts={
                    "phases_to_run": phases_ordered,
                    "change_description": change_description,
                    "affected_areas": affected_areas,
                    "is_change_request": True,
                },
            ),
        )
        await get_bus(phase_input.run_id).publish(msg)
    except Exception as e:
        logger.warning("Bus publish failed: %s", e)

    # Notify client
    notification = (
        f"Change request received. Re-running {len(phases_ordered)} affected phases "
        f"({affected_areas}). Estimated time: {estimate_mins} minutes."
    )

    # Write change request record
    cr_record = {
        "project_id": project_id,
        "change_description": change_description,
        "affected_areas": affected_areas,
        "phases_to_run": phases_ordered,
        "estimate_minutes": estimate_mins,
        "notification": notification,
    }
    cr_path = output_dir / "change_request.json"
    cr_path.write_text(json.dumps(cr_record, indent=2))

    issues = []
    if not phases_ordered:
        issues.append("Could not determine phases to re-run")

    return TaskResult(
        output_path=str(cr_path),
        confidence=0.9 if phases_ordered else 0.2,
        metadata=cr_record,
        issues=issues,
        success=len(phases_ordered) > 0,
    )
