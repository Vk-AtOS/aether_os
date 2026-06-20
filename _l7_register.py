# Layer 7 registration — integrate into orchestrator/phase_sequence.py
#
# This file is NEVER imported by the runtime.  It documents the exact edits
# needed to wire p19_service_catalog into the active pipeline.
#
# ── 1. PHASE_SEQUENCE (orchestrator/phase_sequence.py) ─────────────────────
#
# Insert "p19_service_catalog" AFTER "p15_handoff" (last phase in the list):
#
#   PHASE_SEQUENCE = [
#       ...
#       "p15_handoff",
#       "p19_service_catalog",   # <── add this line
#   ]
#
# ── 2. PHASE_SUPERVISORS (orchestrator/phase_sequence.py) ──────────────────
#
#   PHASE_SUPERVISORS: Dict[str, str] = {
#       ...
#       "p15_handoff": "aether_os.phases.p15_handoff.supervisor_agent.HandoffSupervisor",
#       "p19_service_catalog": "aether_os.phases.p19_service_catalog.supervisor_agent.ServiceCatalogSupervisor",  # <── add
#   }
#
# ── 3. CRITICAL_PHASES ─────────────────────────────────────────────────────
#
# p19 is NOT critical — the pipeline continues even if it is skipped or fails.
# Do NOT add it to CRITICAL_PHASES.
#
# ── 4. p05_frontend/task_agent.py — cloud console fork ─────────────────────
#
# In phases/p05_frontend/task_agent.py, add this block BEFORE the existing
# frontend_framework check (around line 108), right after _bp is assigned:
#
#   if _bp.get("build_type") == "cloud_platform":
#       logger.info("p05: build_type=cloud_platform — routing to cloud_console_generator")
#       from aether_os.phases.p05_frontend.cloud_console_generator import generate_cloud_console
#       _ir_path_str = data.get("domain_ir_path", "")
#       _entities: list = []
#       if _ir_path_str:
#           try:
#               import json as _json
#               _ir_data = _json.loads(Path(_ir_path_str).read_text())
#               _entities = _ir_data.get("entities", [])
#           except Exception as _cc_exc:
#               logger.warning("p05: cloud console IR load failed: %s", _cc_exc)
#       _services = data.get("services") or []
#       _project_name = data.get("project_name", "Cloud Platform")
#       await generate_cloud_console(_entities, _services, _project_name, output_dir)
#       return TaskResult(
#           output_path=str(output_dir / "frontend"),
#           confidence=0.9,
#           metadata={"skipped_standard_react": True, "cloud_console": True},
#           success=True,
#       )
#
# ── 5. core/stack_profiles.py — new build type ─────────────────────────────
#
# Add a new StackProfile to STACK_PROFILES dict:
#
#   "cloud_platform": StackProfile(
#       name="cloud_platform",
#       description="Cloud management console — service catalog, resource explorer, billing dashboard.",
#       build_type="cloud_platform",
#       architecture="monolith",
#       backend_lang="python",
#       backend_framework="fastapi",
#       frontend_framework="react",
#       db_primary="postgres",
#       db_secondary=["redis"],
#       deployment_target="docker_compose",
#       performance_tier="standard",
#   ),

PHASE_SEQUENCE_ADDITIONS = [
    ("after", "p15_handoff", "p19_service_catalog"),  # Cloud console + catalog API
]

PHASE_SUPERVISORS_ADDITIONS = {
    "p19_service_catalog": "aether_os.phases.p19_service_catalog.supervisor_agent.ServiceCatalogSupervisor",
}
