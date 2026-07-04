"""
Stage 8: OBSERVABILITY
======================
PURPOSE: Instrument the generated app with a complete observability stack:
         metrics (Prometheus), dashboards (Grafana), error tracking (Sentry),
         analytics events (PostHog), and alerting (Alertmanager).
         Produces a standalone monitoring/ directory alongside the app.

INPUTS:
  - backend_output_path  : str  — FastAPI src/ to instrument (from Stage 3)
  - healing_passed       : bool — True if app is healthy (skip deep instrumentation if false)
  - domain               : str  — vertical (for domain-specific metrics/alerts)
  - project_name         : str  — used in dashboard titles and alert labels

OUTPUTS:
  - monitoring_path      : str  — path to generated monitoring/ directory
  - prometheus_config    : str  — path to prometheus.yml
  - grafana_dashboards   : list — paths to generated Grafana dashboard JSONs
  - sentry_configured    : bool — True if Sentry DSN env var injected
  - analytics_events     : list — event names registered in analytics_service.py
  - alert_rules_count    : int  — number of alert rules generated

SUB-STEPS:
  1. [SEQUENTIAL] p09_observability    — Prometheus middleware injection into main.py
                                         + OTEL config + prometheus.yml
  2. [PARALLEL]   p11a_monitoring      — Grafana dashboards + monitoring/ directory
                                         (skips main.py injection — already done by p09)
  3. [PARALLEL]   p11b_error_tracking  — Sentry SDK + structlog config
  4. [PARALLEL]   p11c_analytics       — PostHog events + analytics router
  5. [SEQUENTIAL] p11d_alerting        — Alertmanager rules + runbooks
                                         (runs last — references all the above)

FIX FOR DUPLICATE INJECTION: p09_observability writes "add_prometheus_middleware" into
main.py. Before calling p11a_monitoring, we read main.py and check if "prometheus" is
already present. If it is, we set input_data["prometheus_already_injected"] = True.
p11a_monitoring's own injection guard checks for "Instrumentator" already present, so
as long as p09's text is there, p11a's injection block is skipped automatically.

CRITICAL: No — observability failures don't block delivery
"""
from __future__ import annotations

import asyncio
import importlib
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult
from aether_os.core.projects import get_project_manager

logger = logging.getLogger(__name__)

_ALERT_RULE_NAMES = [
    "HighErrorRate",
    "HighLatencyP95",
    "DatabaseConnectionPoolExhausted",
    "ServiceDown",
    "HighMemoryUsage",
    "HighCPUUsage",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prometheus_already_in_main(data: Dict[str, Any]) -> bool:
    """
    Return True if Prometheus middleware is already present in main.py.

    p09_observability writes "add_prometheus_middleware" into main.py.
    p11a_monitoring's injection guard checks for "Instrumentator" in content.
    After p09 runs, "Instrumentator" won't be present but our p09 text will be.
    We flag it so p11a's injection path is pre-empted at the supervisor level.
    """
    for key in ("canonical_src_dir", "backend_src_dir", "backend_output_path"):
        val = data.get(key, "")
        if val:
            main_py = Path(val) / "main.py"
            if not main_py.exists():
                main_py = Path(val).parent / "main.py"
            if main_py.exists():
                content = main_py.read_text()
                return "prometheus" in content.lower() or "Instrumentator" in content
    return False


def _collect_grafana_dashboards(output_dir: Path) -> List[str]:
    """Return paths to all generated Grafana dashboard JSON files."""
    return [str(p) for p in output_dir.rglob("*.json")
            if "dashboard" in p.name or "dashboards" in str(p.parent)]


def _count_alert_rules(output_dir: Path) -> int:
    """Count alert rule entries across all alert_rules.yml files under output_dir."""
    total = 0
    for rules_file in output_dir.rglob("alert_rules.yml"):
        try:
            content = rules_file.read_text()
            total += content.count("- alert:")
        except Exception as exc:
            logger.warning("[s08] could not read %s: %s", rules_file, exc)
    return total


def _sentry_configured(output_dir: Path) -> bool:
    """Return True if any sentry_setup.py or .env.error_tracking was written."""
    return any(output_dir.rglob("sentry_setup.py")) or any(
        output_dir.rglob(".env.error_tracking")
    )


def _analytics_events(output_dir: Path) -> List[str]:
    """Return event constant names from analytics_events.py if present."""
    events: List[str] = []
    for events_file in output_dir.rglob("analytics_events.py"):
        try:
            for line in events_file.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    name = line.split("=")[1].strip().strip('"').strip("'")
                    if name:
                        events.append(name)
        except Exception as exc:
            logger.warning("[s08] could not parse analytics_events.py: %s", exc)
    return events


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

class ObservabilityStageSupervisor(PhaseBase):
    """
    Stage 8 supervisor: instruments the generated app with a full observability
    stack via five sequential/parallel sub-phases.

    Execution order:
      Step 1 (sequential): p09_observability — Prometheus middleware + OTEL
      Steps 2-4 (parallel): p11a_monitoring, p11b_error_tracking, p11c_analytics
      Step 5 (sequential): p11d_alerting — references all of the above

    Duplicate-injection guard: after step 1 we check whether "prometheus" is
    already in main.py.  If yes, we set input_data["prometheus_already_injected"]
    so the p11a injection block (which checks "Instrumentator" in content) is
    naturally skipped — p09's presence satisfies p11a's own guard condition.
    """

    phase_name = "s08_observability"

    async def run_task(self, phase_input: Any, memory_ctx: List[Dict]) -> TaskResult:
        pm = get_project_manager()
        data: Dict[str, Any] = phase_input.input_data or {}
        issues: List[str] = []

        # ── Step 1: p09_observability (sequential) ────────────────────────────
        # Must run first: injects Prometheus middleware + OTEL into main.py.
        p09_result = await self._run_sub_phase(
            phase_module="aether_os.phases.p09_observability.task_agent",
            sub_phase_name="p09_observability",
            phase_input=phase_input,
            memory_ctx=memory_ctx,
            pm=pm,
        )
        if p09_result.issues:
            issues.extend(p09_result.issues)

        # ── Duplicate-injection guard ─────────────────────────────────────────
        # After p09 writes "add_prometheus_middleware" into main.py, flag it so
        # p11a_monitoring sees "prometheus" already present and skips its own
        # injection block (p11a checks "Instrumentator" in content — p09's
        # text satisfies that guard when combined with our flag).
        try:
            if _prometheus_already_in_main(data):
                phase_input.input_data["prometheus_already_injected"] = True
                logger.info(
                    "[s08] prometheus already injected by p09 — p11a will skip main.py patch"
                )
        except Exception as exc:
            logger.warning("[s08] prometheus check failed (non-fatal): %s", exc)

        # ── Steps 2–4: parallel ───────────────────────────────────────────────
        # p11a_monitoring: Grafana dashboards + monitoring/ directory
        # p11b_error_tracking: Sentry + structlog
        # p11c_analytics: PostHog events + analytics router
        parallel_tasks = [
            self._run_sub_phase(
                phase_module="aether_os.phases.p11a_monitoring.task_agent",
                sub_phase_name="p11a_monitoring",
                phase_input=phase_input,
                memory_ctx=memory_ctx,
                pm=pm,
            ),
            self._run_sub_phase(
                phase_module="aether_os.phases.p11b_error_tracking.task_agent",
                sub_phase_name="p11b_error_tracking",
                phase_input=phase_input,
                memory_ctx=memory_ctx,
                pm=pm,
            ),
            self._run_sub_phase(
                phase_module="aether_os.phases.p11c_analytics.task_agent",
                sub_phase_name="p11c_analytics",
                phase_input=phase_input,
                memory_ctx=memory_ctx,
                pm=pm,
            ),
        ]
        p11a_result, p11b_result, p11c_result = await asyncio.gather(*parallel_tasks)

        for r in (p11a_result, p11b_result, p11c_result):
            if r.issues:
                issues.extend(r.issues)

        # ── Step 5: p11d_alerting (sequential, runs last) ─────────────────────
        # Alertmanager rules reference metrics from all prior steps.
        p11d_result = await self._run_sub_phase(
            phase_module="aether_os.phases.p11d_alerting.task_agent",
            sub_phase_name="p11d_alerting",
            phase_input=phase_input,
            memory_ctx=memory_ctx,
            pm=pm,
        )
        if p11d_result.issues:
            issues.extend(p11d_result.issues)

        # ── Mimir high-scale config (optional, non-blocking) ─────────────────
        # When estimated_users > 10000, scale_tier is enterprise/high_traffic,
        # or K8s with high expected_load, generate Grafana Mimir distributed
        # config alongside the standard Prometheus stack.
        outputs: Dict[str, Any] = {}
        estimated_users = data.get("estimated_users", 0) or 0
        scale_tier = data.get("scale_tier", "standard")
        is_k8s = data.get("deployment_target", "") == "kubernetes"
        use_mimir = (
            estimated_users > 10000
            or scale_tier in ("enterprise", "high_traffic")
            or (is_k8s and data.get("expected_load", "") in ("high", "very_high"))
        )
        backend_output_path = data.get("backend_output_path", "") or data.get("project_dir", "")
        project_name = data.get("project_name", "App")
        if use_mimir:
            try:
                from aether_os.phases.p11a_monitoring.mimir_config import (
                    gen_mimir_helm_values,
                    gen_mimir_docker_compose,
                    gen_mimir_config_yaml,
                    gen_cortex_migration_guide,
                )
                from pathlib import Path as _Path
                monitoring_dir = _Path(backend_output_path).parent / "monitoring"
                monitoring_dir.mkdir(parents=True, exist_ok=True)
                (monitoring_dir / "mimir-values.yaml").write_text(
                    gen_mimir_helm_values(project_name)
                )
                (monitoring_dir / "docker-compose.mimir.yml").write_text(
                    gen_mimir_docker_compose(project_name)
                )
                (monitoring_dir / "mimir.yaml").write_text(
                    gen_mimir_config_yaml(project_name)
                )
                (monitoring_dir / "MIMIR_MIGRATION.md").write_text(
                    gen_cortex_migration_guide(project_name)
                )
                logger.info(
                    "[s08] Mimir distributed config generated (estimated_users=%d)",
                    estimated_users,
                )
                outputs["mimir_configured"] = True
                outputs["metrics_backend"] = "mimir"
            except Exception as _mimir_exc:
                logger.warning(
                    "[s08] Mimir config generation failed (non-fatal): %s", _mimir_exc
                )
                outputs["metrics_backend"] = "prometheus"
        else:
            outputs["metrics_backend"] = "prometheus"

        # ── Collect outputs ───────────────────────────────────────────────────
        # Use p11a's output_path as the canonical monitoring_path (it writes
        # the full monitoring/ directory with docker-compose + Grafana).
        monitoring_path = p11a_result.output_path or p09_result.output_path

        # Derive prometheus_config from p09 metadata first, then fallback to
        # a well-known relative location inside the p11a output.
        prometheus_config = p09_result.metadata.get("prometheus_config", "")
        if not prometheus_config and monitoring_path:
            candidate = Path(monitoring_path) / "prometheus.yml"
            if candidate.exists():
                prometheus_config = str(candidate)

        # Scan outputs for Grafana dashboards, alert rule count, etc.
        base_output = Path(monitoring_path) if monitoring_path else Path("/tmp")
        grafana_dashboards = _collect_grafana_dashboards(base_output)
        alert_rules_count = _count_alert_rules(base_output)

        # Also scan p11d's output directory
        p11d_out = Path(p11d_result.output_path) if p11d_result.output_path else None
        if p11d_out and p11d_out.exists():
            alert_rules_count += _count_alert_rules(p11d_out)

        sentry_ok = _sentry_configured(base_output)
        analytics_ev = _analytics_events(base_output)

        logger.info(
            "[s08] complete: monitoring_path=%s grafana_dashboards=%d "
            "alert_rules=%d sentry=%s analytics_events=%d",
            monitoring_path,
            len(grafana_dashboards),
            alert_rules_count,
            sentry_ok,
            len(analytics_ev),
        )

        return TaskResult(
            output_path=monitoring_path or "",
            confidence=0.85,
            metadata={
                "monitoring_path": monitoring_path,
                "prometheus_config": prometheus_config,
                "grafana_dashboards": grafana_dashboards,
                "sentry_configured": sentry_ok,
                "analytics_events": analytics_ev,
                "alert_rules_count": alert_rules_count,
                "project_name": project_name,
                "metrics_backend": outputs.get("metrics_backend", "prometheus"),
                "mimir_configured": outputs.get("mimir_configured", False),
                "sub_steps": {
                    "p09_observability": p09_result.success,
                    "p11a_monitoring": p11a_result.success,
                    "p11b_error_tracking": p11b_result.success,
                    "p11c_analytics": p11c_result.success,
                    "p11d_alerting": p11d_result.success,
                },
            },
            issues=issues,
            # Observability failures never block delivery (spec: CRITICAL: No)
            success=True,
        )

    async def validate_gate(self, result: TaskResult, phase_input: Any) -> GateOutcome:
        """
        Gate: passes if a prometheus.yml and at least one Grafana dashboard exist.
        Observability failures are non-blocking — warn only, never fail the pipeline.
        """
        monitoring_path = result.metadata.get("monitoring_path", "")
        prometheus_config = result.metadata.get("prometheus_config", "")
        grafana_dashboards: List[str] = result.metadata.get("grafana_dashboards", [])
        gate_issues: List[str] = []

        if not monitoring_path or not Path(monitoring_path).exists():
            gate_issues.append(
                f"s08_observability: monitoring directory not found at {monitoring_path!r}"
            )

        if not prometheus_config or not Path(prometheus_config).exists():
            gate_issues.append(
                "s08_observability: prometheus.yml was not generated"
            )

        if not grafana_dashboards:
            gate_issues.append(
                "s08_observability: no Grafana dashboard JSONs were generated"
            )

        if gate_issues:
            # Non-blocking: log warnings but pass the gate
            for issue in gate_issues:
                logger.warning("[s08] gate warning: %s", issue)
            return GateOutcome(
                passed=True,  # Observability failures don't block delivery
                issues=gate_issues,
                confidence=0.6,
            )

        return GateOutcome(
            passed=True,
            confidence=result.confidence,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _run_sub_phase(
        self,
        phase_module: str,
        sub_phase_name: str,
        phase_input: Any,
        memory_ctx: List[Dict],
        pm: Any,
    ) -> TaskResult:
        """Import a phase task_agent module by dotted path and call run()."""
        output_dir = pm.get_output_dir(phase_input.project_id, sub_phase_name)
        try:
            mod = importlib.import_module(phase_module)
            result: TaskResult = await mod.run(phase_input, memory_ctx, output_dir)
            logger.info(
                "[s08] %s: success=%s confidence=%.2f issues=%d",
                sub_phase_name, result.success, result.confidence, len(result.issues),
            )
            return result
        except Exception as exc:
            logger.warning("[s08] %s failed (non-critical): %s", sub_phase_name, exc)
            return TaskResult(
                output_path=str(output_dir),
                confidence=0.0,
                metadata={"skipped": True, "error": str(exc)},
                issues=[f"{sub_phase_name} raised: {exc}"],
                success=False,
            )
