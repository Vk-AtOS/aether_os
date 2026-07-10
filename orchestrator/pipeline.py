"""
AetherOS — Main Pipeline Orchestrator (DEPRECATED)

.. deprecated::
    Use :mod:`orchestrator.factory_pipeline` instead.
    ``orchestrator.pipeline`` is the legacy 10-phase orchestrator retained only
    for backward-compatible test coverage. All new work should target
    ``orchestrator.factory_pipeline.FactoryPipeline``.

Key improvements (historical):
- Uses unified LLM client (Anthropic primary)
- Uses PipelineStateMachine for state tracking
- BUG 9 FIX: write_output_to_disk() writes generated code to output_dir
- Uses persistent MemoryStore instead of in-memory dict
- All phases go through PhaseGate validation

Phase implementations live in pipeline_helpers.py to keep this file under
600 lines.
"""
from __future__ import annotations

import warnings as _warnings
_warnings.warn(
    "orchestrator.pipeline is deprecated; use orchestrator.factory_pipeline instead.",
    DeprecationWarning,
    stacklevel=2,
)

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from aether_os.orchestrator.context import ExecutionContext, PhaseOutput
from aether_os.orchestrator.state_machine import PipelineStateMachine, PipelineState
from aether_os.core.audit.ledger import get_ledger
from aether_os.core.llm.client import get_llm_client
from aether_os.orchestrator.pipeline_helpers import (
    write_output_to_disk,
    phase_requirements,
    phase_architecture,
    phase_scaffolding,
    phase_codegen,
    phase_review,
    phase_security,
    phase_testing,
    phase_cicd,
    phase_docs,
    phase_observability,
    phase_packaging,
)

logger = logging.getLogger(__name__)


class Pipeline:
    """
    Main AetherOS pipeline orchestrator.

    Runs a 10-phase pipeline from NL requirement to packaged output.
    Integrates:
    - PipelineStateMachine (state tracking + audit)
    - Stall monitor (via orchestrator/monitor.py)
    - Phase gates (pass/fail with retry)
    - Persistent memory (MemoryStore)
    - Unified LLM client (Anthropic + Ollama fallback)

    Phase logic lives in pipeline_helpers.py.
    """

    def __init__(self) -> None:
        self.llm = get_llm_client()
        self.ledger = get_ledger()

    # Bind phase helpers as instance methods
    _phase_requirements = phase_requirements
    _phase_architecture = phase_architecture
    _phase_scaffolding = phase_scaffolding
    _phase_codegen = phase_codegen
    _phase_review = phase_review
    _phase_security = phase_security
    _phase_testing = phase_testing
    _phase_cicd = phase_cicd
    _phase_docs = phase_docs
    _phase_observability = phase_observability
    _phase_packaging = phase_packaging

    async def run(
        self,
        requirement: str,
        project_name: str = "untitled",
        language: str = "python",
        output_dir: Optional[str] = None,
        max_retries: int = 3,
        org_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run the full pipeline from requirement to packaged output.

        Returns a result dict with status, run_id, output artifacts, and errors.
        """
        from aether_os.core.config.loader import get_config
        cfg = get_config()

        ctx_kwargs = dict(
            requirement=requirement,
            project_name=project_name,
            language=language,
            output_dir=output_dir,
            max_retries=max_retries or cfg.get("pipeline.max_retries", 3),
            org_id=org_id,
        )
        if run_id:
            ctx_kwargs["run_id"] = run_id
        ctx = ExecutionContext(**ctx_kwargs)

        sm = PipelineStateMachine(run_id=ctx.run_id)
        self.ledger.save_run(ctx.run_id, f"pipeline: {requirement[:50]}", org_id=org_id, status="running")

        logger.info("Pipeline starting [run=%s] requirement=%s", ctx.run_id, requirement[:60])
        pipeline_start = time.time()

        # Start stall monitor
        try:
            from aether_os.orchestrator.monitor import get_pipeline_monitor
            thresholds = cfg.get("pipeline.stage_timeout_seconds", {})
            get_pipeline_monitor().start_monitoring(ctx.run_id, thresholds)
        except Exception as exc:
            logger.warning("Could not start stall monitor: %s", exc)

        try:
            sm.transition_to(PipelineState.REQUIREMENTS, reason="pipeline start")
            await self._phase_requirements(ctx, sm)

            sm.transition_to(PipelineState.ARCHITECTURE, reason="requirements complete")
            await self._phase_architecture(ctx, sm)

            sm.transition_to(PipelineState.SCAFFOLDING, reason="architecture complete")
            await self._phase_scaffolding(ctx, sm)

            # Codegen + Review + Security + Testing retry loop
            retries = 0
            while retries < ctx.max_retries:
                sm.transition_to(PipelineState.BACKEND_CODEGEN, reason=f"codegen attempt {retries+1}")
                await self._phase_codegen(ctx, sm, retries=retries)

                # Thread through 26-phase sequence: BACKEND_CODEGEN→UIUX_DESIGN→…→CODE_REVIEW
                for _mid in (PipelineState.UIUX_DESIGN, PipelineState.FRONTEND_CODEGEN,
                              PipelineState.COMPONENT_LIBRARY, PipelineState.INTEGRATION):
                    sm.transition_to(_mid, reason="pass-through")

                sm.transition_to(PipelineState.CODE_REVIEW, reason="codegen complete")
                await self._phase_review(ctx, sm)

                sm.transition_to(PipelineState.SECURITY, reason="review complete")
                security_passed = await self._phase_security(ctx, sm)

                if not security_passed and retries < ctx.max_retries - 1:
                    logger.warning("Security check failed, retrying codegen (attempt %d)", retries + 1)
                    self.ledger.log_event(ctx.run_id, "pipeline", "security_retry", {"attempt": retries + 1})
                    retries += 1
                    continue

                sm.transition_to(PipelineState.UNIT_TESTING, reason="security complete")
                test_passed = await self._phase_testing(ctx, sm)

                if not test_passed and retries < ctx.max_retries - 1:
                    logger.warning("Tests failed, retrying codegen (attempt %d)", retries + 1)
                    self.ledger.log_event(ctx.run_id, "pipeline", "test_retry", {"attempt": retries + 1})
                    retries += 1
                    continue

                break

            if retries >= ctx.max_retries:
                raise RuntimeError(
                    f"Max retries ({ctx.max_retries}) exceeded in codegen/verification loop."
                )

            # Thread through remaining intermediate states to CICD
            for _mid in (PipelineState.PERF_TESTING, PipelineState.A11Y_TESTING,
                          PipelineState.E2E_TESTING):
                sm.transition_to(_mid, reason="pass-through")

            sm.transition_to(PipelineState.CICD, reason="testing complete")
            # Run CI/CD, Docs, and Observability in parallel after Testing
            await asyncio.gather(
                self._phase_cicd(ctx, sm),
                self._phase_docs(ctx, sm),
                self._phase_observability(ctx, sm),
            )

            sm.transition_to(PipelineState.DOCUMENTATION, reason="CI/CD complete")

            sm.transition_to(PipelineState.DEPLOYMENT, reason="docs complete")
            await self._phase_packaging(ctx, sm)

            # Thread through post-deployment monitoring/observability states
            for _mid in (PipelineState.MONITORING, PipelineState.ERROR_TRACKING,
                          PipelineState.ANALYTICS, PipelineState.ALERTING,
                          PipelineState.FEATURE_FLAGS, PipelineState.AB_TESTING,
                          PipelineState.APP_MEMORY, PipelineState.CLIENT_PORTAL):
                sm.transition_to(_mid, reason="pass-through")

            # BUG 9 FIX: Write all artifacts to disk
            output_path = await write_output_to_disk(ctx)

            # Autonomous self-testing (only when org has autonomous_mode enabled)
            if ctx.org_id:
                from aether_os.core.db import get_session_factory
                from aether_os.core.models import Organisation
                from sqlalchemy import select
                async with get_session_factory()() as session:
                    stmt = select(Organisation).where(Organisation.id == ctx.org_id)
                    result = await session.execute(stmt)
                    org = result.scalar_one_or_none()
                    if org and org.autonomous_mode:
                        test_phase_output = getattr(ctx, "test_results", None) or {}
                        security_findings = []
                        if hasattr(ctx, "review_findings") and ctx.review_findings:
                            try:
                                findings = ctx.review_findings if isinstance(ctx.review_findings, list) else []
                                security_findings = [f for f in findings if isinstance(f, dict) and f.get("severity") in ("HIGH", "CRITICAL")]
                            except Exception as exc:
                                logger.debug("security_findings filter failed (non-fatal): %s", exc)

                        ctx.self_test_report = {
                            "tests_passed": test_phase_output.get("tests_passed", 0),
                            "tests_failed": test_phase_output.get("tests_failed", 0),
                            "endpoints_tested": test_phase_output.get("endpoints_tested", 0),
                            "security_findings": len(security_findings),
                            "performance_baseline": test_phase_output.get("performance_baseline", {}),
                            "coverage_percent": test_phase_output.get("coverage_percent", 0),
                        }
                        from aether_os.core.models import Run
                        from sqlalchemy import update
                        stmt = update(Run).where(Run.id == ctx.run_id).values(self_test_report=json.dumps(ctx.self_test_report))
                        await session.execute(stmt)
                        await session.commit()

            # Generate project memory
            from aether_os.core.memory.memory_manager import MemoryManager
            MemoryManager.save_project_memory(Path(output_path), {
                "project_id": ctx.run_id,
                "project_name": ctx.project_name,
                "domain": ctx.domain,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "tech_stack": ctx.tech_stack,
                "changelog": [{"date": time.strftime("%Y-%m-%d"), "entry": "Initial generation", "author": "AetherOS"}]
            })

            sm.transition_to(PipelineState.COMPLETE, reason="all phases complete")
            self.ledger.update_run_status(ctx.run_id, "completed")

            duration = time.time() - pipeline_start
            logger.info(
                "Pipeline COMPLETE [run=%s] duration=%.1fs output=%s",
                ctx.run_id, duration, output_path,
            )

            return {
                "status": "complete",
                "run_id": ctx.run_id,
                "output_dir": output_path,
                "requirement": ctx.requirement,
                "requirements_doc": ctx.requirements_doc,
                "architecture_doc": ctx.architecture_doc,
                "generated_code": ctx.generated_code,
                "review_findings": ctx.review_findings,
                "security_report": ctx.security_report,
                "test_results": ctx.test_results,
                "docs": ctx.docs,
                "phases": [p.model_dump() for p in ctx.phase_outputs],
                "duration_seconds": round(duration, 2),
            }

        except Exception as exc:
            ctx.add_error(str(exc))
            try:
                sm.transition_to(PipelineState.FAILED, reason=str(exc))
            except Exception as sm_exc:
                logger.debug("State machine transition to FAILED failed (non-fatal): %s", sm_exc)
            self.ledger.update_run_status(ctx.run_id, "failed")
            logger.error("Pipeline FAILED [run=%s]: %s", ctx.run_id, exc)
            return {
                "status": "failed",
                "run_id": ctx.run_id,
                "error": str(exc),
                "errors": ctx.errors,
                "phases": [p.model_dump() for p in ctx.phase_outputs],
            }

        finally:
            try:
                from aether_os.orchestrator.monitor import get_pipeline_monitor
                get_pipeline_monitor().stop_monitoring()
            except Exception as exc:
                logger.debug("Pipeline monitor stop_monitoring failed (non-fatal): %s", exc)


_pipeline_instance: Optional[Pipeline] = None


def get_pipeline() -> Pipeline:
    """Return the global singleton Pipeline instance."""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = Pipeline()
    return _pipeline_instance
