"""
Stage 9: DEVOPS
===============
PURPOSE: Generate a complete DevOps package: Docker containerization, CI/CD pipeline,
         Kubernetes manifests, and cloud deployment infrastructure. The generated app
         gets a Dockerfile, GitHub Actions CI workflow, K8s Helm chart, and
         optionally Terraform AWS configs.

INPUTS:
  - backend_output_path   : str   — FastAPI src/ (from Stage 3)
  - frontend_output_path  : str   — React src/ (from Stage 4)
  - healing_passed        : bool  — if False, still generate DevOps but mark as unverified
  - architecture_decisions: dict  — cloud target, deployment strategy
  - project_name          : str   — used in Helm chart names, CI workflow names
  - build_profile         : dict  — deployment_target: "docker" | "kubernetes" | "serverless"

OUTPUTS:
  - dockerfile_path       : str   — path to generated Dockerfile
  - ci_workflow_path      : str   — path to .github/workflows/ci.yml
  - helm_chart_path       : str   — path to Helm chart directory (if k8s target)
  - terraform_path        : str   — path to Terraform configs (if cloud target)
  - live_url              : str   — URL if app was deployed (from p11_deployment)
  - backend_port          : int   — port the app is running on
  - k8s_manifests         : list  — paths to K8s YAML files

SUB-STEPS:
  1. [SEQUENTIAL] p08_cicd_deployment  — Dockerfile + GitHub Actions CI
  2. [SEQUENTIAL] p11_deployment       — Docker build + run + basic K8s manifests
  3. [CONDITIONAL] p11e_enterprise     — Helm + Terraform + CD workflow
                                         (only if deployment_target == "kubernetes"
                                          or architecture in ["microservices","event_driven"])

NOTE: p08_cicd_deployment is a thin wrapper around p08_cicd. We call
      p08_cicd_deployment directly — it resolves the CICDAgent indirection internally.

CRITICAL: No — a crash does not end the run.
GATE: blocks when no Dockerfile was generated or the attempted deploy failed (KAN-247).
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional  # noqa: F401 — Optional used throughout

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult
from aether_os.core.projects import get_project_manager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Condition checks
# ---------------------------------------------------------------------------

def _should_run_enterprise(build_profile: Dict[str, Any],
                            architecture_decisions: Dict[str, Any]) -> bool:
    """
    Run p11e_enterprise_deployment when:
      - build_profile.deployment_target == "kubernetes", OR
      - build_profile.architecture in ("microservices", "event_driven"), OR
      - architecture_decisions contains a kubernetes/cloud strategy
    """
    deployment_target = build_profile.get("deployment_target", "docker")
    architecture = build_profile.get("architecture", "monolith")

    if deployment_target == "kubernetes":
        return True
    if architecture in ("microservices", "event_driven"):
        return True

    # Also check architecture_decisions dict (from Stage 2)
    arch_strategy = architecture_decisions.get("deployment_strategy", "")
    if "kubernetes" in arch_strategy.lower() or "k8s" in arch_strategy.lower():
        return True

    return False


# ---------------------------------------------------------------------------
# Output extraction helpers
# ---------------------------------------------------------------------------

def _find_dockerfile(output_dir: Optional[Path], project_dir: Optional[Path] = None) -> str:
    """Return path to generated Dockerfile, searching output_dir then project_dir."""
    for search_root in filter(None, [output_dir, project_dir]):
        for df in Path(search_root).rglob("Dockerfile"):
            return str(df)
    return ""


def _find_ci_workflow(output_dir: Optional[Path], project_dir: Optional[Path] = None) -> str:
    """Return path to generated GitHub Actions workflow YAML."""
    for search_root in filter(None, [output_dir, project_dir]):
        for wf in Path(search_root).rglob("*.yml"):
            if ".github" in str(wf) and "workflow" in str(wf).lower():
                return str(wf)
        for wf in Path(search_root).rglob("ci.yml"):
            return str(wf)
    return ""


def _find_helm_chart(output_dir: Path) -> str:
    """Return path to generated Helm chart directory (contains Chart.yaml)."""
    for chart_yaml in output_dir.rglob("Chart.yaml"):
        return str(chart_yaml.parent)
    return ""


def _find_terraform(output_dir: Path) -> str:
    """Return path to Terraform configs directory."""
    for tf_file in output_dir.rglob("*.tf"):
        return str(tf_file.parent)
    return ""


def _find_k8s_manifests(output_dir: Path) -> List[str]:
    """Return paths to all K8s YAML manifests (deployment/service/ingress)."""
    k8s_keywords = ("deployment", "service", "ingress", "configmap", "secret", "manifest")
    manifests: List[str] = []
    for yml_file in output_dir.rglob("*.yaml"):
        if any(kw in yml_file.name.lower() for kw in k8s_keywords):
            manifests.append(str(yml_file))
    for yml_file in output_dir.rglob("*.yml"):
        if any(kw in yml_file.name.lower() for kw in k8s_keywords):
            manifests.append(str(yml_file))
    return manifests


def _deploy_status(p11_result: TaskResult, live_url: str) -> Dict[str, Any]:
    """{"state": "deployed" | "failed" | "not_deployed", "reason", "live_url"} from p11's result.

    p11 reports success+skipped when Docker is not available (nothing was attempted) and success=False when the
    build, the run or the /health wait failed or there was nothing to deploy.
    """
    meta = p11_result.metadata or {}
    if not p11_result.success:
        reason = meta.get("error") or meta.get("failure_reason") or "; ".join(
            str(i) for i in (p11_result.issues or [])[:1]) or "p11_deployment reported failure"
        return {"state": "failed", "reason": str(reason)[:500], "live_url": None}
    if meta.get("skipped") or not live_url:
        return {"state": "not_deployed", "reason": str(meta.get("message") or "no live URL was produced")[:300],
                "live_url": None}
    return {"state": "deployed", "reason": "", "live_url": live_url}


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

class DevOpsStageSupervisor(PhaseBase):
    """
    Stage 9 supervisor: generates a full DevOps package in three sequential steps.

    Step 1 (sequential): p08_cicd_deployment — Dockerfile + GitHub Actions CI.
      p08_cicd_deployment is a thin wrapper that calls the CICDAgent internally.

    Step 2 (sequential): p11_deployment — Docker build + run + K8s manifests.
      Produces a live_url and backend_port if Docker is available.

    Step 3 (conditional): p11e_enterprise_deployment — Helm + Terraform + CD.
      Only runs when deployment_target="kubernetes" or architecture is
      microservices/event_driven. Skipped for simple docker targets.

    DevOps failures are non-blocking (CRITICAL: No).
    """

    phase_name = "s09_devops"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        pm = get_project_manager()
        data: Dict[str, Any] = phase_input.input_data or {}
        build_profile: Dict[str, Any] = data.get("build_profile") or {}
        architecture_decisions: Dict[str, Any] = data.get("architecture_decisions") or {}
        issues: List[str] = []

        # ── Step 1: p08_cicd_deployment (sequential) ─────────────────────────
        # Generates Dockerfile + GitHub Actions CI workflow.
        # p08_cicd_deployment wraps CICDAgent from p08_cicd internally.
        p08_result = await self._run_sub_phase(
            phase_module="aether_os.phases.p08_cicd_deployment.task_agent",
            sub_phase_name="p08_cicd_deployment",
            phase_input=phase_input,
            memory_ctx=memory_ctx,
            pm=pm,
        )
        if p08_result.issues:
            issues.extend(p08_result.issues)

        # ── Step 2: p11_deployment (sequential) ──────────────────────────────
        # Docker build + run (if Docker available) + writes K8s manifests.
        # Produces live_url and backend_port.
        p11_result = await self._run_sub_phase(
            phase_module="aether_os.phases.p11_deployment.task_agent",
            sub_phase_name="p11_deployment",
            phase_input=phase_input,
            memory_ctx=memory_ctx,
            pm=pm,
        )
        if p11_result.issues:
            issues.extend(p11_result.issues)

        # Extract live_url and port from p11's metadata or TaskAgent dict result
        live_url: str = (
            p11_result.metadata.get("live_url")
            or p11_result.metadata.get("output", {}).get("live_url", "")
            or ""
        )
        backend_port: int = (
            p11_result.metadata.get("port")
            or p11_result.metadata.get("output", {}).get("port", 0)
            or 0
        )

        # ── Step 3: p11e_enterprise_deployment (conditional) ─────────────────
        # Helm + Terraform + CD workflow. Only for kubernetes/microservices builds.
        p11e_result: Optional[TaskResult] = None
        run_enterprise = _should_run_enterprise(build_profile, architecture_decisions)
        if run_enterprise:
            logger.info(
                "[s09] deployment_target=%s architecture=%s — running p11e_enterprise",
                build_profile.get("deployment_target", "docker"),
                build_profile.get("architecture", "monolith"),
            )
            p11e_result = await self._run_sub_phase(
                phase_module="aether_os.phases.p11e_enterprise_deployment.task_agent",
                sub_phase_name="p11e_enterprise_deployment",
                phase_input=phase_input,
                memory_ctx=memory_ctx,
                pm=pm,
            )
            if p11e_result.issues:
                issues.extend(p11e_result.issues)
        else:
            logger.info(
                "[s09] p11e_enterprise skipped "
                "(deployment_target=%s architecture=%s — not kubernetes/microservices)",
                build_profile.get("deployment_target", "docker"),
                build_profile.get("architecture", "monolith"),
            )

        # ── Collect outputs ───────────────────────────────────────────────────
        # Scan all sub-phase output directories to locate generated artifacts.
        p08_out = Path(p08_result.output_path) if p08_result.output_path else None
        p11_out = Path(p11_result.output_path) if p11_result.output_path else None
        p11e_out = Path(p11e_result.output_path) if p11e_result and p11e_result.output_path else None

        dockerfile_path = ""
        ci_workflow_path = ""
        helm_chart_path = ""
        terraform_path = ""
        k8s_manifests: List[str] = []

        # Search p08 output for Dockerfile + CI workflow
        if p08_out and p08_out.exists():
            dockerfile_path = _find_dockerfile(p08_out)
            ci_workflow_path = _find_ci_workflow(p08_out)

        # Search project dir too (p11 writes Dockerfile alongside main.py)
        project_dir_path: Optional[Path] = None
        run_id = getattr(phase_input, "run_id", None)
        if run_id:
            import os
            project_dir_path = Path(os.path.expanduser(f"~/.aether_os/projects/{run_id}"))

        if not dockerfile_path:
            dockerfile_path = _find_dockerfile(
                p11_out, project_dir_path
            )
        if not ci_workflow_path:
            ci_workflow_path = _find_ci_workflow(
                p11_out, project_dir_path
            )

        # K8s manifests from p11 output
        if p11_out and p11_out.exists():
            k8s_manifests = _find_k8s_manifests(p11_out)

        # Helm + Terraform from p11e output
        if p11e_out and p11e_out.exists():
            helm_chart_path = _find_helm_chart(p11e_out)
            terraform_path = _find_terraform(p11e_out)
            if not ci_workflow_path:
                ci_workflow_path = _find_ci_workflow(p11e_out)
            k8s_manifests += _find_k8s_manifests(p11e_out)

        project_name = data.get("project_name", "App")
        healing_passed = data.get("healing_passed", True)
        deploy = _deploy_status(p11_result, live_url)

        logger.info(
            "[s09] complete: dockerfile=%s ci=%s helm=%s terraform=%s "
            "live_url=%s port=%s k8s_manifests=%d enterprise=%s",
            bool(dockerfile_path),
            bool(ci_workflow_path),
            bool(helm_chart_path),
            bool(terraform_path),
            live_url or "none",
            backend_port or "none",
            len(k8s_manifests),
            run_enterprise,
        )

        return TaskResult(
            output_path=str(p11_out or p08_out or ""),
            confidence=0.85 if (dockerfile_path and ci_workflow_path) else 0.6,
            metadata={
                "dockerfile_path": dockerfile_path,
                "ci_workflow_path": ci_workflow_path,
                "helm_chart_path": helm_chart_path,
                "terraform_path": terraform_path,
                "live_url": live_url,
                "backend_port": backend_port,
                "k8s_manifests": k8s_manifests,
                "healing_passed": healing_passed,
                "enterprise_deployed": run_enterprise,
                "deploy": deploy,
                "not_verified": ([f"deploy: not run: {deploy['reason']}"] if deploy["state"] == "not_deployed" else []),
                "project_name": project_name,
                "sub_steps": {
                    "p08_cicd_deployment": p08_result.success,
                    "p11_deployment": p11_result.success,
                    "p11e_enterprise_deployment": (
                        p11e_result.success if p11e_result else None
                    ),
                },
            },
            issues=issues,
            # A crash is not critical (the stage is non-critical); a failed deploy is decided by the gate.
            success=True,
        )

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """
        Gate: blocks when no Dockerfile was generated or the deploy was attempted and the app did not come up
        (docker build/run failed or /health never answered). This gate used to pass in every case, so a run whose
        container never started still reached "completed" (KAN-247). A deploy that could not be attempted (no
        Docker here) does not block; it is listed in metadata["not_verified"]. A missing CI workflow is a warning.
        """
        meta = result.metadata or {}
        dockerfile_path = meta.get("dockerfile_path", "")
        blocking: List[str] = []
        if not dockerfile_path or not Path(dockerfile_path).exists():
            blocking.append("s09_devops: Dockerfile was not generated — Docker build/run will not be possible")
        deploy = meta.get("deploy") or {}
        if deploy.get("state") == "failed":
            blocking.append(f"s09_devops: deploy failed: {deploy.get('reason') or 'no reason given'}")
        if blocking:
            return GateOutcome(passed=False, issues=blocking, confidence=result.confidence)

        warnings: List[str] = list(meta.get("not_verified") or [])
        ci_workflow_path = meta.get("ci_workflow_path", "")
        if not ci_workflow_path or not Path(ci_workflow_path).exists():
            warnings.append("s09_devops: GitHub Actions CI workflow was not generated")
        for issue in warnings:
            logger.warning("[s09] gate warning: %s", issue)
        return GateOutcome(passed=True, issues=warnings, confidence=0.6 if warnings else result.confidence)

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _run_sub_phase(
        self,
        phase_module: str,
        sub_phase_name: str,
        phase_input: Any,
        memory_ctx: List[Dict],
        pm: Any,
    ) -> TaskResult:
        """
        Import a phase task_agent module and invoke run() or the class-based TaskAgent.

        p08_cicd_deployment and p11_deployment both expose a top-level run() function
        (p08_cicd_deployment wraps CICDAgent internally; p11_deployment uses a TaskAgent
        class but its supervisor_agent.py exposes run()).  We use the task_agent.run()
        function consistently across all sub-phases here.
        """
        output_dir = pm.get_output_dir(phase_input.project_id, sub_phase_name)
        try:
            mod = importlib.import_module(phase_module)

            # p11_deployment uses a TaskAgent class, not a module-level run()
            if sub_phase_name == "p11_deployment":
                agent = mod.TaskAgent()
                raw = await agent.run(phase_input)
                # Normalise dict result into TaskResult
                return TaskResult(
                    output_path=str(raw.get("output_file", raw.get("output_path", output_dir))),
                    confidence=0.85 if raw.get("success") else 0.3,
                    metadata=raw,
                    issues=raw.get("issues", []),
                    success=raw.get("success", False),
                )

            result: TaskResult = await mod.run(phase_input, memory_ctx, output_dir)
            logger.info(
                "[s09] %s: success=%s confidence=%.2f issues=%d",
                sub_phase_name, result.success, result.confidence, len(result.issues),
            )
            return result

        except Exception as exc:
            logger.warning("[s09] %s failed (non-critical): %s", sub_phase_name, exc)
            return TaskResult(
                output_path=str(output_dir),
                confidence=0.0,
                metadata={"skipped": True, "error": str(exc)},
                issues=[f"{sub_phase_name} raised: {exc}"],
                success=False,
            )

