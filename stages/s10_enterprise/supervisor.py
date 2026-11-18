"""
Stage 10: ENTERPRISE
====================
PURPOSE: Add enterprise-grade capabilities to the generated app: feature flags for
         safe rollouts, A/B testing for experimentation, persistent app memory,
         IAM/authorization policies, billing/metering integration, K8s operator
         for self-management, and an SRE agent for autonomous incident response.

INPUTS:
  - backend_output_path   : str  — FastAPI src/ (from Stage 3)
  - permission_model      : dict — ABAC model (from Stage 2) — used by IAM
  - architecture_decisions: dict — determines if K8s operator is needed
  - healing_passed        : bool — if False, extensions still generated but flagged

OUTPUTS:
  - feature_flags_path    : str  — path to feature_flags/ directory
  - ab_testing_path       : str  — path to ab_testing/ directory
  - memory_service_path   : str  — path to memory/ directory
  - iam_policies_path     : str  — path to OPA Rego policies + Keycloak realm
  - billing_path          : str  — path to billing/metering scaffold
  - k8s_operator_path     : str  — path to K8s operator (if kubernetes target)
  - sre_agent_path        : str  — path to SRE CronJob + runbooks

SUB-STEPS (all run in parallel — they write to different directories):
  1. [PARALLEL] p12a_feature_flags    — JSON-file feature flag router (percentage canary, rings); not Unleash
  2. [PARALLEL] p12b_ab_testing       — self-contained experiment/variant template; not GrowthBook
  3. [PARALLEL] p13_app_memory        — memory service: ChromaDB, else postgres text rows, else a JSON file; not mem0
  4. [PARALLEL] p16_iam               — OPA Rego policies + Keycloak realm JSON
  5. [PARALLEL] p18_billing_metering  — OpenMeter + Stripe billing scaffold
  6. [PARALLEL] p21_sre_agent         — K8s CronJob + failure classifier + runbooks
  7. [CONDITIONAL] p17_control_plane  — K8s Operator + CRDs
                                        (only if architecture in ["microservices","event_driven"]
                                         or deployment_target == "kubernetes")

CRITICAL: No — enterprise extensions are additive, never block delivery
"""
from __future__ import annotations

import ast
import asyncio
import copy
import importlib
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult

logger = logging.getLogger(__name__)

# Architectures that trigger the conditional K8s operator phase
_K8S_ARCHITECTURES = {"microservices", "event_driven"}

# ---------------------------------------------------------------------------
# Enterprise extension routers
# ---------------------------------------------------------------------------
# Each entry: (phase, package, router module, import alias).
# A sub-phase writes <its own output dir>/<package>/..., NOT into the app: the old table looked for
# the files under the app's src/, where they never are, so nothing was ever wired. The package is
# copied into src/ and then included. p16_iam writes policy files only (no router), so it is not here.
_ENTERPRISE_ROUTERS: List[Tuple[str, str, str, str]] = [
    ("p12a_feature_flags", "feature_flags", "flag_admin_router", "_ff_router"),
    ("p12b_ab_testing", "ab_testing", "ab_router", "_ab_router"),
    ("p18_billing_metering", "billing", "billing_webhook", "_billing_router"),
]


def _autowire_enterprise_extensions(
    backend_src: Path, succeeded_phases: List[str], phase_dirs: Dict[str, Path]
) -> List[str]:
    """Copy each generated extension package into the app's src/ and include its router in main.py.

    The patched main.py is validated with ast.parse before it is written; an extension whose
    snippet breaks the file is skipped. Returns the packages that are wired.
    """
    main_py_path = backend_src / "main.py"
    if not main_py_path.exists():
        logger.warning("s10 autowire: main.py not found at %s — skipping", main_py_path)
        return []

    original_main = main_py_path.read_text(encoding="utf-8")
    patched_main = original_main
    wired: List[str] = []

    for phase, package, router_module, alias in _ENTERPRISE_ROUTERS:
        if phase not in succeeded_phases:
            continue
        src_pkg = phase_dirs.get(phase, Path("/nonexistent")) / package
        dest_pkg = backend_src / package
        if not (src_pkg / f"{router_module}.py").exists() and not (dest_pkg / f"{router_module}.py").exists():
            logger.warning("s10 autowire: %s has no %s/%s.py — not wired", phase, package, router_module)
            continue
        if src_pkg.is_dir():
            dest_pkg.mkdir(parents=True, exist_ok=True)
            for py in src_pkg.glob("*.py"):
                shutil.copy2(py, dest_pkg / py.name)
            (dest_pkg / "__init__.py").touch()

        import_path = f"{package}.{router_module}"
        if import_path in patched_main:
            wired.append(package)  # idempotent: already wired
            continue
        # main.py imports the app's modules by plain name (src/ is on sys.path), so the same here.
        snippet = (
            f"\n# Enterprise extension: {package} (auto-wired by s10)\n"
            f"try:\n"
            f"    from {import_path} import router as {alias}\n"
            f"    app.include_router({alias}, prefix=\"/api\")\n"
            f"except Exception as _autowire_{package}_exc:\n"
            f"    logging.getLogger(__name__).warning("
            f"'s10 autowire: {package} router unavailable: %s', _autowire_{package}_exc)\n"
        )
        try:
            ast.parse(patched_main + snippet)
        except SyntaxError as syn_exc:
            logger.warning("s10 autowire: patched main.py fails ast.parse for '%s' — skipping: %s", package, syn_exc)
            continue
        patched_main += snippet
        wired.append(package)
        logger.info("s10 autowire: wired enterprise extension '%s' into main.py", package)

    if patched_main != original_main:
        main_py_path.write_text(patched_main, encoding="utf-8")
        logger.info("s10 autowire: main.py updated with %d extension(s): %s", len(wired), wired)
    return wired


STAGE_CONTRACT = {
    "stage": "s10_enterprise",
    "display_name": "Enterprise",
    "critical": False,
    "parallel_substeps": [
        "p12a_feature_flags",
        "p12b_ab_testing",
        "p13_app_memory",
        "p16_iam",
        "p18_billing_metering",
        "p21_sre_agent",
    ],
    "conditional_substeps": ["p17_control_plane"],
    "inputs": [
        "backend_output_path",
        "permission_model",
        "architecture_decisions",
        "healing_passed",
    ],
    "outputs": [
        "feature_flags_path",
        "ab_testing_path",
        "memory_service_path",
        "iam_policies_path",
        "billing_path",
        "k8s_operator_path",
        "sre_agent_path",
    ],
}


class EnterpriseStageSupervisor(PhaseBase):
    """Consolidated supervisor for Stage 10 (Enterprise).

    Runs 6 enterprise extension phases in parallel via asyncio.gather,
    then conditionally runs the K8s operator phase if the architecture warrants it.
    All failures are logged and surfaced as issues — none block delivery.
    """

    phase_name = "s10_enterprise"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        from aether_os.core.projects import get_project_manager
        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        data: dict = phase_input.input_data or {}
        issues: List[str] = []

        # Warn if healing did not pass — extensions are still generated
        if not data.get("healing_passed", True):
            logger.warning(
                "s10_enterprise: healing_passed=False — enterprise extensions "
                "generated but flagged as running on unhealed codebase"
            )
            issues.append("healing_passed=False: enterprise extensions may target broken code")

        # ── Parallel: 6 enterprise sub-phases ────────────────────────────────
        parallel_phases = [
            "p12a_feature_flags",
            "p12b_ab_testing",
            "p13_app_memory",
            "p16_iam",
            "p18_billing_metering",
            "p21_sre_agent",
        ]

        parallel_tasks = [
            self._run_sub_phase(name, phase_input, memory_ctx, pm)
            for name in parallel_phases
        ]
        parallel_results = await asyncio.gather(*parallel_tasks, return_exceptions=True)

        # Map phase name → result for output key extraction
        results: Dict[str, Any] = {}
        output_key_map = {
            "p12a_feature_flags": "feature_flags_path",
            "p12b_ab_testing": "ab_testing_path",
            "p13_app_memory": "memory_service_path",
            "p16_iam": "iam_policies_path",
            "p18_billing_metering": "billing_path",
            "p21_sre_agent": "sre_agent_path",
        }

        for phase_name, result in zip(parallel_phases, parallel_results):
            if isinstance(result, Exception):
                logger.warning("s10: %s raised exception (non-critical): %s", phase_name, result)
                issues.append(f"{phase_name} failed: {result}")
                results[phase_name] = None
            elif isinstance(result, TaskResult):
                results[phase_name] = result
                out_key = output_key_map.get(phase_name)
                if out_key and result.output_path:
                    phase_input.input_data[out_key] = result.output_path
                if not result.success:
                    logger.warning("s10: %s returned success=False", phase_name)
                    issues.append(f"{phase_name} reported success=False")
            else:
                logger.warning("s10: %s returned unexpected type: %s", phase_name, type(result))
                results[phase_name] = None

        # ── Conditional: p17_control_plane ────────────────────────────────────
        # Runs after gather because it depends on architecture decisions, not
        # on any of the parallel outputs above.
        build_profile: dict = data.get("build_profile") or {}
        arch_decisions: dict = data.get("architecture_decisions") or {}
        architecture = (
            build_profile.get("architecture")
            or arch_decisions.get("architecture")
            or ""
        )
        deployment_target = (
            build_profile.get("deployment_target")
            or arch_decisions.get("deployment_target")
            or ""
        )

        k8s_operator_triggered = (
            architecture in _K8S_ARCHITECTURES
            or deployment_target == "kubernetes"
        )

        if k8s_operator_triggered:
            logger.info(
                "s10_enterprise: triggering p17_control_plane "
                "(architecture=%s, deployment_target=%s)",
                architecture, deployment_target,
            )
            try:
                op_result = await self._run_sub_phase(
                    "p17_control_plane", phase_input, memory_ctx, pm
                )
                results["p17_control_plane"] = op_result
                if isinstance(op_result, TaskResult) and op_result.output_path:
                    phase_input.input_data["k8s_operator_path"] = op_result.output_path
                if isinstance(op_result, TaskResult) and not op_result.success:
                    issues.append("p17_control_plane reported success=False")
            except Exception as e:
                logger.warning("s10: p17_control_plane failed (non-critical): %s", e)
                issues.append(f"p17_control_plane failed: {e}")
        else:
            logger.info(
                "s10_enterprise: p17_control_plane skipped "
                "(architecture=%s, deployment_target=%s)",
                architecture, deployment_target,
            )

        # ── Summarise ─────────────────────────────────────────────────────────
        succeeded = [
            name for name, r in results.items()
            if isinstance(r, TaskResult) and r.success
        ]
        failed = [
            name for name, r in results.items()
            if r is None or (isinstance(r, TaskResult) and not r.success)
        ]

        metadata = {
            "succeeded": succeeded,
            "failed": failed,
            "k8s_operator_triggered": k8s_operator_triggered,
            "healing_passed": data.get("healing_passed", True),
            "output_paths": {
                key: phase_input.input_data.get(key)
                for key in output_key_map.values()
            },
        }
        if k8s_operator_triggered:
            metadata["output_paths"]["k8s_operator_path"] = phase_input.input_data.get(
                "k8s_operator_path"
            )

        confidence = len(succeeded) / max(len(results), 1)

        # ── Auto-wire enterprise routers into the generated app's main.py ────
        backend_src_path = data.get("backend_output_path") or data.get("backend_src_dir")
        if backend_src_path:
            backend_src = Path(backend_src_path)
            # Treat succeeded phase names as the list of features that were generated
            try:
                phase_dirs = {n: pm.get_output_dir(phase_input.project_id, n) for n in succeeded}
                autowired = _autowire_enterprise_extensions(backend_src, succeeded, phase_dirs)
                metadata["autowired_extensions"] = autowired
                logger.info(
                    "s10_enterprise: auto-wired %d enterprise extension(s): %s",
                    len(autowired), autowired,
                )
            except Exception as aw_exc:
                logger.warning("s10_enterprise: autowire failed (non-blocking): %s", aw_exc)
                metadata["autowired_extensions"] = []
        else:
            logger.info("s10_enterprise: no backend_src_dir in context — autowire skipped")
            metadata["autowired_extensions"] = []

        logger.info(
            "s10_enterprise: complete — %d/%d sub-phases succeeded",
            len(succeeded), len(results),
        )

        return TaskResult(
            output_path=str(output_dir),
            confidence=confidence,
            metadata=metadata,
            issues=issues,
            success=True,  # Never blocks delivery
        )

    async def _run_sub_phase(
        self, phase_name: str, phase_input: Any, memory_ctx: list, pm
    ) -> TaskResult:
        """Import and call a legacy phase's task_agent.run() in its own output dir."""
        mod = importlib.import_module(f"aether_os.phases.{phase_name}.task_agent")
        sub_input = copy.copy(phase_input)
        sub_input.input_data = copy.deepcopy(phase_input.input_data)
        output_dir: Path = pm.get_output_dir(phase_input.project_id, phase_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        return await mod.run(sub_input, memory_ctx, output_dir)

    async def validate_gate(
        self, result: TaskResult, phase_input: Any
    ) -> GateOutcome:
        # Enterprise stage is non-critical: gate always passes.
        # Partial failures are surfaced via result.issues for observability.
        if result.issues:
            logger.warning(
                "s10_enterprise gate: %d issue(s) noted (non-blocking): %s",
                len(result.issues), result.issues,
            )
        return GateOutcome(
            passed=True,
            issues=result.issues,
            confidence=result.confidence,
        )
