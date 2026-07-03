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
  1. [PARALLEL] p12a_feature_flags    — Unleash feature flag router + admin UI
  2. [PARALLEL] p12b_ab_testing       — GrowthBook experiment framework
  3. [PARALLEL] p13_app_memory        — mem0 memory layer + knowledge graph
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
from pathlib import Path
from typing import Any, Dict, List, Tuple

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult

logger = logging.getLogger(__name__)

# Architectures that trigger the conditional K8s operator phase
_K8S_ARCHITECTURES = {"microservices", "event_driven"}

# ---------------------------------------------------------------------------
# Router file discovery map for enterprise extensions
# ---------------------------------------------------------------------------
# Each entry: (feature_key, [candidate relative paths], import_alias, router_var)
_ENTERPRISE_ROUTER_CANDIDATES: List[Tuple[str, List[str], str, str]] = [
    (
        "feature_flags",
        ["feature_flags/flag_admin_router.py", "feature_flags_router.py"],
        "_ff_router",
        "router",
    ),
    (
        "iam",
        ["iam/router.py", "iam_router.py"],
        "_iam_router",
        "router",
    ),
    (
        "billing",
        ["billing/billing_webhook.py", "billing_router.py"],
        "_billing_router",
        "router",
    ),
    (
        "ab_testing",
        ["ab_testing/ab_router.py", "ab_testing_router.py"],
        "_ab_router",
        "router",
    ),
]


def _autowire_enterprise_extensions(
    backend_src: Path, features_generated: List[str]
) -> List[str]:
    """Patch the generated app's main.py to include enterprise extension routers.

    For each feature in features_generated, searches for the router file at known
    candidate paths relative to backend_src. If found and not already wired into
    main.py, appends a try/except include_router block. Validates the patched file
    with ast.parse() before writing — skips the extension if parsing fails.

    Returns a list of extension names that were successfully wired.
    """
    main_py_path = backend_src / "main.py"
    if not main_py_path.exists():
        logger.warning("s10 autowire: main.py not found at %s — skipping", main_py_path)
        return []

    original_main = main_py_path.read_text(encoding="utf-8")
    patched_main = original_main
    wired: List[str] = []

    for feature_key, candidates, alias, router_var in _ENTERPRISE_ROUTER_CANDIDATES:
        # Only wire features that were actually generated in this run
        if not any(feature_key in f for f in features_generated):
            continue

        # Find first existing candidate router file
        found_path: Path | None = None
        for candidate in candidates:
            candidate_path = backend_src / candidate
            if candidate_path.exists():
                found_path = candidate_path
                break

        if found_path is None:
            logger.debug("s10 autowire: no router file found for feature '%s' — skipped", feature_key)
            continue

        # Derive Python import path relative to src/ (replace / with . and strip .py)
        rel_import = str(found_path.relative_to(backend_src)).replace("/", ".").removesuffix(".py")

        # Skip if already wired (idempotency)
        if rel_import in patched_main or alias in patched_main:
            logger.debug("s10 autowire: '%s' already wired into main.py — skipped", feature_key)
            wired.append(feature_key)
            continue

        snippet = (
            f"\n# Enterprise extension: {feature_key} (auto-wired by s10)\n"
            f"try:\n"
            f"    from {rel_import} import {router_var} as {alias}\n"
            f"    app.include_router({alias}, prefix=\"/api\")\n"
            f"except Exception as _autowire_{feature_key}_exc:\n"
            f"    import logging as _awl\n"
            f"    _awl.getLogger(__name__).warning("
            f"'s10 autowire: {feature_key} router unavailable: %s', _autowire_{feature_key}_exc)\n"
        )

        candidate_patched = patched_main + snippet

        # Validate with ast.parse before committing
        try:
            ast.parse(candidate_patched)
        except SyntaxError as syn_exc:
            logger.warning(
                "s10 autowire: patched main.py fails ast.parse for '%s' — skipping: %s",
                feature_key, syn_exc,
            )
            continue

        patched_main = candidate_patched
        wired.append(feature_key)
        logger.info("s10 autowire: wired enterprise extension '%s' into main.py", feature_key)

    if patched_main != original_main:
        try:
            main_py_path.write_text(patched_main, encoding="utf-8")
            logger.info("s10 autowire: main.py updated with %d extension(s): %s", len(wired), wired)
        except Exception as write_exc:
            logger.error("s10 autowire: failed to write patched main.py: %s", write_exc)

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
                autowired = _autowire_enterprise_extensions(backend_src, succeeded)
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
