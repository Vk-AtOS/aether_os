"""
AetherOS — Stage sequence definitions and supervisor loader.

The pipeline is organised into 12 clean stages. Each stage is a supervisor
that internally orchestrates its sub-phases (parallel where possible).
Individual phase directories still exist under phases/ and are called by
their parent stage supervisor — they are NOT registered here directly.
"""
from __future__ import annotations

import importlib
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# Stages whose failure must abort the pipeline.
# Stages 3+ (quality, testing, observability, devops, enterprise, handoff,
# specialist) are intentionally non-critical — failures produce partial
# deliverables rather than pipeline aborts.
CRITICAL_PHASES = frozenset({
    "s01_intake",       # no requirements → nothing to build
    "s02_architecture", # no Domain IR → all codegen falls back to stubs
    "s03_backend",      # no backend → frontend integration fails completely
})

# Legacy phase directories that exist on disk but are now managed internally
# by their parent stage supervisor. Never add these directly to PHASE_SEQUENCE.
INACTIVE_PHASE_DIRS = frozenset({
    # dead (no task_agent, never called) — deleted in stage consolidation
    # kept here so any stale code that checks this set doesn't crash
    "p00_intake", "p00a_intake", "p01_requirements", "p09_documentation",
    # absorbed into stage supervisors — run internally, not by the orchestrator
    "p00_research", "p00b_data_archaeology", "p00c_architecture_planner",
    "p01_intake_requirements", "p01b_integration_discovery",
    "p02_architecture", "p02b_domain_ir", "p02c_permission_modeling",
    "p03_scaffolding",
    "p04_backend", "p04a_backend_codegen", "p04_uiux_design",
    "p04b_business_logic", "p04c_integration_codegen",
    "p05_frontend", "p05b_mobile", "p05c_desktop", "p05d_cli", "p05e_serverless",
    "p06_review_security", "p06b_formal_verification",
    "p07_testing", "p07a_unit_testing", "p07b_performance_testing",
    "p07c_accessibility_testing", "p07d_e2e_testing",
    "p07b_self_healing",
    "p08_cicd", "p08_cicd_deployment",
    "p09_observability", "p11a_monitoring", "p11b_error_tracking",
    "p11c_analytics", "p11d_alerting",
    "p11_deployment", "p11e_enterprise_deployment",
    "p12a_feature_flags", "p12b_ab_testing", "p13_app_memory",
    "p14_client_portal", "p15_handoff",
    "p16_iam", "p17_control_plane", "p18_billing_metering",
    "p19_service_catalog", "p20_multiregion", "p21_sre_agent",
    "p10_docs_delivery",
})

# ── 12-Stage pipeline sequence ─────────────────────────────────────────────────
#
#  Stage  │ Name          │ What it does
# ────────┼───────────────┼──────────────────────────────────────────────────────
#  s01    │ INTAKE        │ Requirements, domain research, past-run archaeology
#  s02    │ ARCHITECTURE  │ Domain IR, permission model, project scaffold
#  s03    │ BACKEND       │ FastAPI: models, CRUD, business logic, integrations
#  s04    │ FRONTEND      │ React/Vite/TanStack + conditional platform outputs
#  s05    │ QUALITY GATE  │ Security scan, Z3 proofs, 8-dimension artifact scoring
#  s06    │ TESTING       │ Unit, performance, accessibility, E2E (all parallel)
#  s07    │ SELF-HEALING  │ 4-layer health probe + autonomous repair
#  s08    │ OBSERVABILITY │ Prometheus, Grafana, Sentry, analytics, alerting
#  s09    │ DEVOPS        │ CI/CD, Docker, K8s manifests, Helm, Terraform
#  s10    │ ENTERPRISE    │ Feature flags, A/B, memory, IAM, billing, SRE
#  s11    │ HANDOFF       │ Docs, client portal, Postman, delivery ZIP
#  s12    │ SPECIALIST    │ Mobile, desktop, CLI, serverless (all conditional)
# ────────┴───────────────┴──────────────────────────────────────────────────────
PHASE_SEQUENCE = [
    "s01_intake",        # INTAKE        — requirements + research + past-run mining
    "s02_architecture",  # ARCHITECTURE  — Domain IR + permission model + scaffold
    "s03_backend",       # BACKEND       — complete FastAPI backend
    "s04_frontend",      # FRONTEND      — React/Vite/TanStack + platform variants
    "s05_quality",       # QUALITY GATE  — security + Z3 + dimension scoring
    "s06_testing",       # TESTING       — unit + perf + a11y + E2E (parallel)
    "s07_healing",       # SELF-HEALING  — 4-layer probe + autonomous repair
    "s08_observability", # OBSERVABILITY — Prometheus + Grafana + Sentry + alerts
    "s09_devops",        # DEVOPS        — CI/CD + Docker + K8s + Helm + Terraform
    "s10_enterprise",    # ENTERPRISE    — feature flags + IAM + billing + SRE agent
    "s11_handoff",       # HANDOFF       — docs + portal + Postman + delivery ZIP
    "s12_specialist",    # SPECIALIST    — mobile + desktop + CLI + serverless (cond.)
]

# Stage name → supervisor class path.
# All paths use the "aether_os.stages.*" namespace.
# _load_supervisor() also tries "stages.*" as a fallback for bare source-tree runs.
PHASE_SUPERVISORS: Dict[str, str] = {
    "s01_intake":        "aether_os.stages.s01_intake.supervisor.IntakeStageSupervisor",
    "s02_architecture":  "aether_os.stages.s02_architecture.supervisor.ArchitectureStageSupervisor",
    "s03_backend":       "aether_os.stages.s03_backend.supervisor.BackendStageSupervisor",
    "s04_frontend":      "aether_os.stages.s04_frontend.supervisor.FrontendStageSupervisor",
    "s05_quality":       "aether_os.stages.s05_quality.supervisor.QualityGateSupervisor",
    "s06_testing":       "aether_os.stages.s06_testing.supervisor.TestingStageSupervisor",
    "s07_healing":       "aether_os.stages.s07_healing.supervisor.HealingStageSupervisor",
    "s08_observability": "aether_os.stages.s08_observability.supervisor.ObservabilityStageSupervisor",
    "s09_devops":        "aether_os.stages.s09_devops.supervisor.DevOpsStageSupervisor",
    "s10_enterprise":    "aether_os.stages.s10_enterprise.supervisor.EnterpriseStageSupervisor",
    "s11_handoff":       "aether_os.stages.s11_handoff.supervisor.HandoffStageSupervisor",
    "s12_specialist":    "aether_os.stages.s12_specialist.supervisor.SpecialistStageSupervisor",
}


def _load_supervisor(phase_name: str):
    """Dynamically import and instantiate the supervisor for a stage.

    Tries the configured path first ("aether_os.stages.<stage>...") and falls
    back to "stages.<stage>..." if the aether_os package isn't installed
    (i.e. running from the source tree without `pip install -e .`).
    """
    class_path = PHASE_SUPERVISORS.get(phase_name)
    if not class_path:
        return None
    candidates = [class_path]
    # bare source-tree fallback: strip "aether_os." prefix
    if class_path.startswith("aether_os."):
        candidates.append(class_path[len("aether_os."):])
    last_exc: Exception | None = None
    for path in candidates:
        module_path, class_name = path.rsplit(".", 1)
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            if not callable(cls):
                raise TypeError(f"{path} is not callable — expected a Supervisor class")
            return cls()
        except (ImportError, AttributeError, TypeError) as exc:
            last_exc = exc
            logger.debug("[pipeline] supervisor candidate %r failed: %s", path, exc)
    logger.error(
        "[pipeline] Cannot load supervisor for stage %r — tried %s. Last error: %s",
        phase_name, candidates, last_exc,
    )
    raise last_exc  # type: ignore
