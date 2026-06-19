"""
AetherOS — Phase sequence definitions and supervisor loader.

Extracted from factory_pipeline.py to keep that module focused on
orchestration logic rather than phase registry data.
"""
from __future__ import annotations

import importlib
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# Phases whose failure must abort the pipeline — downstream phases depend on their output.
# Self-healing (p07b) and observational phases (p08+) are deliberately excluded so
# they don't block delivery on non-critical failures.
CRITICAL_PHASES = frozenset({
    "p01_intake_requirements",  # no requirements → nothing to build
    "p02_architecture",         # no architecture → codegen produces garbage
    "p02b_domain_ir",           # no IR → p04/p05 fall back to "items" stub everywhere
    "p04_backend",              # no backend → p05 integration fails completely
    "p05_frontend",             # no frontend → deliverable is unusable
})

# Phase directories that exist on disk but are NOT registered in PHASE_SUPERVISORS
# and are therefore never executed by the active pipeline.  These are legacy
# validator / gate-testing utilities from a v1→v2 consolidation.  Do not add
# them to PHASE_SEQUENCE or PHASE_SUPERVISORS without implementing the
# corresponding *Supervisor class.
INACTIVE_PHASE_DIRS = frozenset({
    "p00_intake",
    "p01_requirements",
    "p04a_backend_codegen",
    "p04b_uiux_design",
    "p07a_unit_testing",
    "p07b_performance_testing",
    "p07c_accessibility_testing",
    "p07d_e2e_testing",
})

# Ordered 24-phase sequence (12 core + 8 post-deployment + p00_research + p04b_business_logic + p07b_self_healing + p00c)
PHASE_SEQUENCE = [
    "p00_research",
    "p00b_data_archaeology",        # Analyze existing schema + generate ETL migration scripts
    "p00c_architecture_planner",    # Microservices service map (skips for monolith builds)
    "p01_intake_requirements",
    "p01b_integration_discovery",   # Discover external systems needed (after intake)
    "p02_architecture",
    "p02b_domain_ir",
    "p02c_permission_modeling",  # ABAC permission model derived from domain IR
    "p03_scaffolding",
    "p04_backend",
    "p04b_business_logic",
    "p04c_integration_codegen",     # Generate async clients for discovered integrations
    "p05_frontend",
    "p05b_mobile",               # React Native (Expo) app — skips for non-mobile builds
    "p06_review_security",
    "p07_testing",
    "p07b_self_healing",
    "p08_cicd_deployment",
    "p09_observability",
    "p10_docs_delivery",
    "p11_deployment",       # Docker build & run — delivers a live URL
    "p11a_monitoring",      # Prometheus + Grafana + OTEL
    "p11b_error_tracking",  # Sentry + structlog
    "p11c_analytics",       # PostHog events + dashboard
    "p11d_alerting",        # Alertmanager + runbooks
    "p11e_enterprise_deployment",  # Helm charts, Terraform, operational scripts
    "p12a_feature_flags",   # Unleash feature flags
    "p12b_ab_testing",      # GrowthBook experiments
    "p13_app_memory",       # mem0 memory layer + knowledge graph
    "p14_client_portal",    # Standalone client review portal
    "p15_handoff",          # Complete technical delivery package (docs, runbook, Postman)
]

# Phase name → supervisor class path (29 phases: see PHASE_SEQUENCE above).
# All paths use the "aether_os.phases.*" namespace. The aether_os package is
# mapped to the repo root via pyproject.toml (`package-dir = {"aether_os" = "."}`).
# _load_supervisor() also adds a fallback to "phases.*" in case the package
# wasn't installed with `pip install -e .` — see _load_supervisor below.
PHASE_SUPERVISORS: Dict[str, str] = {
    "p00_research":              "aether_os.phases.p00_research.supervisor_agent.ResearchSupervisor",
    "p00b_data_archaeology":     "aether_os.phases.p00b_data_archaeology.supervisor_agent.DataArchaeologySupervisor",
    "p00c_architecture_planner": "aether_os.phases.p00c_architecture_planner.supervisor_agent.ArchitecturePlannerSupervisor",
    "p01_intake_requirements":   "aether_os.phases.p01_intake_requirements.IntakeRequirementsSupervisor",
    "p01b_integration_discovery": "aether_os.phases.p01b_integration_discovery.supervisor_agent.IntegrationDiscoverySupervisor",
    "p02_architecture":        "aether_os.phases.p02_architecture.ArchitectureSupervisor",
    "p02b_domain_ir":          "aether_os.phases.p02b_domain_ir.DomainIRSupervisor",
    "p02c_permission_modeling": "aether_os.phases.p02c_permission_modeling.supervisor_agent.PermissionModelingSupervisor",
    "p03_scaffolding":         "aether_os.phases.p03_scaffolding.ScaffoldingSupervisor",
    "p04_backend":             "aether_os.phases.p04_backend.BackendSupervisor",
    "p04b_business_logic":     "aether_os.phases.p04b_business_logic.supervisor_agent.BusinessLogicSupervisor",
    "p04c_integration_codegen": "aether_os.phases.p04c_integration_codegen.supervisor_agent.IntegrationCodegenSupervisor",
    "p05_frontend":            "aether_os.phases.p05_frontend.FrontendSupervisor",
    "p05b_mobile":             "aether_os.phases.p05b_mobile.supervisor_agent.MobileSupervisor",
    "p06_review_security":     "aether_os.phases.p06_review_security.ReviewSecuritySupervisor",
    "p07_testing":             "aether_os.phases.p07_testing.TestingSupervisor",
    "p07b_self_healing":       "aether_os.phases.p07b_self_healing.SelfHealingSupervisor",
    "p08_cicd_deployment":     "aether_os.phases.p08_cicd_deployment.CICDDeploymentSupervisor",
    "p09_observability":       "aether_os.phases.p09_observability.ObservabilitySupervisor",
    "p10_docs_delivery":       "aether_os.phases.p10_docs_delivery.DocsDeliverySupervisor",
    "p11_deployment":          "aether_os.phases.p11_deployment.DeploymentSupervisor",
    # Post-deployment phases
    "p11a_monitoring":         "aether_os.phases.p11a_monitoring.MonitoringSupervisor",
    "p11b_error_tracking":     "aether_os.phases.p11b_error_tracking.ErrorTrackingSupervisor",
    "p11c_analytics":          "aether_os.phases.p11c_analytics.AnalyticsSupervisor",
    "p11d_alerting":           "aether_os.phases.p11d_alerting.AlertingSupervisor",
    "p11e_enterprise_deployment": "aether_os.phases.p11e_enterprise_deployment.supervisor_agent.EnterpriseDeploymentSupervisor",
    "p12a_feature_flags":      "aether_os.phases.p12a_feature_flags.FeatureFlagsSupervisor",
    "p12b_ab_testing":         "aether_os.phases.p12b_ab_testing.ABTestingSupervisor",
    "p13_app_memory":          "aether_os.phases.p13_app_memory.AppMemorySupervisor",
    "p14_client_portal":       "aether_os.phases.p14_client_portal.ClientPortalSupervisor",
    "p15_handoff":             "aether_os.phases.p15_handoff.supervisor_agent.HandoffSupervisor",
}


def _load_supervisor(phase_name: str):
    """Dynamically import and instantiate the supervisor for a phase.

    Tries the configured path first ("aether_os.phases.<phase>...") and falls
    back to "phases.<phase>..." if the aether_os package isn't installed
    (i.e. running from the source tree without `pip install -e .`).
    """
    class_path = PHASE_SUPERVISORS.get(phase_name)
    if not class_path:
        return None
    candidates = [class_path]
    if class_path.startswith("aether_os.phases."):
        candidates.append(class_path[len("aether_os."):])  # → phases.<phase>...
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
        "[pipeline] Cannot load supervisor for phase %r — tried %s. Last error: %s",
        phase_name, candidates, last_exc,
    )
    raise last_exc  # type: ignore
