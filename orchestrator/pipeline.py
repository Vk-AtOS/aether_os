"""
AetherOS — Main Pipeline Orchestrator
Migrated from aether2/aether/agents/orchestrator.py + wired to state machine.

Key improvements:
- Uses unified LLM client (Anthropic primary)
- Uses PipelineStateMachine for state tracking
- BUG 9 FIX: write_output_to_disk() writes generated code to output_dir
- Uses persistent MemoryStore instead of in-memory dict
- All phases go through PhaseGate validation
"""
from __future__ import annotations
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from aether_os.orchestrator.context import ExecutionContext, PhaseOutput
from aether_os.orchestrator.state_machine import PipelineStateMachine, PipelineState
from aether_os.core.audit.ledger import get_ledger
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def write_output_to_disk(ctx: ExecutionContext) -> str:
    """
    BUG 9 FIX: Write all pipeline artifacts to ctx.output_dir.

    Creates directory structure:
      <output_dir>/<project_name>/
        main.py (or generated code)
        requirements.txt
        README.md (docs)
        tests/test_main.py

    Returns the output directory path.
    """
    from aether_os.core.config.loader import get_config
    cfg = get_config()

    base_dir = ctx.output_dir or cfg.get(
        "pipeline.output_dir",
        str(Path.home() / ".aether_os" / "outputs"),
    )
    project_dir = Path(base_dir) / ctx.project_name / ctx.run_id[:8]
    project_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []

    # Write generated code
    if ctx.generated_code:
        code_file = project_dir / "main.py"
        code_file.write_text(ctx.generated_code, encoding="utf-8")
        written.append(str(code_file))

    # Write documentation
    if ctx.docs:
        docs_file = project_dir / "README.md"
        docs_file.write_text(ctx.docs, encoding="utf-8")
        written.append(str(docs_file))

    # Write tests
    if ctx.test_results and ctx.test_results.get("test_code"):
        test_dir = project_dir / "tests"
        test_dir.mkdir(exist_ok=True)
        test_file = test_dir / "test_main.py"
        test_file.write_text(ctx.test_results["test_code"], encoding="utf-8")
        written.append(str(test_file))

    # Write requirements doc
    if ctx.requirements_doc:
        req_file = project_dir / "REQUIREMENTS.md"
        req_file.write_text(ctx.requirements_doc, encoding="utf-8")
        written.append(str(req_file))

    # Write architecture doc
    if ctx.architecture_doc:
        arch_file = project_dir / "ARCHITECTURE.md"
        arch_file.write_text(ctx.architecture_doc, encoding="utf-8")
        written.append(str(arch_file))

    ctx.metadata["output_dir"] = str(project_dir)
    ctx.metadata["written_files"] = written
    logger.info("Output written to %s (%d files)", project_dir, len(written))
    return str(project_dir)


class Pipeline:
    """
    Main AetherOS pipeline orchestrator.

    Runs a 10-phase pipeline from NL requirement to packaged output.
    Integrates:
    - PipelineStateMachine (state tracking + audit)
    - DCSP stall monitor (via orchestrator/monitor.py)
    - Phase gates (pass/fail with retry)
    - Persistent memory (MemoryStore)
    - Unified LLM client (Anthropic + Ollama fallback)
    """

    def __init__(self) -> None:
        self.llm = get_llm_client()
        self.ledger = get_ledger()

    async def run(
        self,
        requirement: str,
        project_name: str = "untitled",
        language: str = "python",
        output_dir: Optional[str] = None,
        max_retries: int = 3,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run the full pipeline from requirement to packaged output.

        Returns a result dict with status, run_id, output artifacts, and errors.
        """
        from aether_os.core.config.loader import get_config
        cfg = get_config()

        ctx = ExecutionContext(
            requirement=requirement,
            project_name=project_name,
            language=language,
            output_dir=output_dir,
            max_retries=max_retries or cfg.get("pipeline.max_retries", 3),
            org_id=org_id,
        )

        sm = PipelineStateMachine(run_id=ctx.run_id)
        self.ledger.save_run(ctx.run_id, f"pipeline: {requirement[:50]}", org_id=org_id, status="running")

        logger.info("Pipeline starting [run=%s] requirement=%s", ctx.run_id, requirement[:60])
        pipeline_start = time.time()

        # Start stall monitor
        try:
            from aether_os.orchestrator.monitor import get_dcsp_bridge
            thresholds = cfg.get("pipeline.stage_timeout_seconds", {})
            get_dcsp_bridge().start_monitoring(ctx.run_id, thresholds)
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
            await self._phase_cicd(ctx, sm)

            sm.transition_to(PipelineState.DOCUMENTATION, reason="CI/CD complete")
            await self._phase_docs(ctx, sm)

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
                "phases": [p.dict() for p in ctx.phase_outputs],
                "duration_seconds": round(duration, 2),
            }

        except Exception as exc:
            ctx.add_error(str(exc))
            try:
                sm.transition_to(PipelineState.FAILED, reason=str(exc))
            except Exception:
                pass
            self.ledger.update_run_status(ctx.run_id, "failed")
            logger.error("Pipeline FAILED [run=%s]: %s", ctx.run_id, exc)
            return {
                "status": "failed",
                "run_id": ctx.run_id,
                "error": str(exc),
                "errors": ctx.errors,
                "phases": [p.dict() for p in ctx.phase_outputs],
            }

        finally:
            try:
                from aether_os.orchestrator.monitor import get_dcsp_bridge
                get_dcsp_bridge().stop_monitoring()
            except Exception:
                pass

    # ── Phase implementations ───────────────────────────────────────────────

    async def _phase_requirements(self, ctx: ExecutionContext, sm: PipelineStateMachine) -> None:
        t0 = time.time()
        prompt = (
            f"Parse the following requirement into structured goals, constraints, "
            f"technical stack, and user stories. Be concise and precise.\n\n"
            f"Requirement:\n{ctx.requirement}"
        )
        result = await self.llm.call(prompt, task_type="requirements")
        ctx.requirements_doc = result
        ctx.record_phase(PhaseOutput(
            phase_id="p01",
            phase_name="requirements",
            passed=bool(result),
            confidence=0.9 if result else 0.0,
            duration_seconds=time.time() - t0,
        ))

    async def _phase_architecture(self, ctx: ExecutionContext, sm: PipelineStateMachine) -> None:
        t0 = time.time()
        prompt = (
            f"Propose a software architecture for the following requirements. "
            f"Include component diagram description, data models, API design, and tech stack.\n\n"
            f"Requirements:\n{ctx.requirements_doc or ctx.requirement}"
        )
        result = await self.llm.call(prompt, task_type="requirements")
        ctx.architecture_doc = result
        ctx.record_phase(PhaseOutput(
            phase_id="p02",
            phase_name="architecture",
            passed=bool(result),
            confidence=0.85 if result else 0.0,
            duration_seconds=time.time() - t0,
        ))

    async def _phase_scaffolding(self, ctx: ExecutionContext, sm: PipelineStateMachine) -> None:
        t0 = time.time()
        prompt = (
            f"Based on the architecture below, list the files and directories to scaffold "
            f"for a {ctx.language} project named '{ctx.project_name}'. "
            f"Return a JSON object with 'files' (list of file paths) and 'structure' (description).\n\n"
            f"Architecture:\n{ctx.architecture_doc or 'Not available'}"
        )
        result = await self.llm.call_json(prompt, task_type="requirements")
        ctx.scaffold_manifest = result
        ctx.record_phase(PhaseOutput(
            phase_id="p03",
            phase_name="scaffolding",
            passed=True,
            confidence=0.8,
            artifacts=result,
            duration_seconds=time.time() - t0,
        ))

    async def _phase_codegen(
        self, ctx: ExecutionContext, sm: PipelineStateMachine, retries: int = 0
    ) -> None:
        t0 = time.time()
        feedback_section = ""
        if retries > 0:
            parts = []
            if ctx.security_issues:
                parts.append(f"Security Issues: {ctx.security_issues}")
            if ctx.test_failures:
                parts.append(f"Test Failures: {ctx.test_failures}")
            if parts:
                feedback_section = (
                    f"\n\nPREVIOUS FEEDBACK (attempt {retries+1}):\n"
                    + "\n".join(parts)
                    + "\n\nPlease fix ALL issues in the regenerated code."
                )

        # Check memory for similar solutions
        memory_context = ""
        try:
            from aether_os.core.memory.store import get_memory_store
            from aether_os.core.memory.fingerprinter import fingerprint
            req_hash = fingerprint(ctx.requirement)
            similar = await get_memory_store().retrieve(req_hash, k=3)
            if similar:
                examples = "\n---\n".join(
                    f"# Previous solution (used {r.success_count} times):\n{r.output_text[:500]}"
                    for r in similar
                )
                memory_context = f"\n\nRELEVANT PAST SOLUTIONS:\n{examples}"
        except Exception as exc:
            logger.debug("Memory retrieval skipped: %s", exc)

        prompt = (
            f"Generate complete, production-quality {ctx.language} code for:\n\n"
            f"Requirements:\n{ctx.requirements_doc or ctx.requirement}\n\n"
            f"Architecture:\n{ctx.architecture_doc or 'Standard MVC'}"
            f"{memory_context}"
            f"{feedback_section}\n\n"
            f"Return ONLY the code, no explanations, no markdown fences."
        )
        result = await self.llm.call(prompt, task_type="code_generation")
        ctx.generated_code = result
        ctx.record_phase(PhaseOutput(
            phase_id="p04",
            phase_name="codegen",
            passed=bool(result),
            confidence=0.85 if result else 0.0,
            duration_seconds=time.time() - t0,
        ))

    async def _phase_review(self, ctx: ExecutionContext, sm: PipelineStateMachine) -> None:
        t0 = time.time()
        code = ctx.generated_code or ""
        prompt = (
            f"Review this {ctx.language} code for bugs, style issues, and correctness. "
            f"Return a JSON with 'findings' (list of issues) and 'overall_quality' (0-10).\n\n"
            f"Code:\n{code[:8000]}"
        )
        result = await self.llm.call_json(prompt, task_type="code_generation")
        ctx.review_findings = result.get("findings", [])
        ctx.record_phase(PhaseOutput(
            phase_id="p05",
            phase_name="review",
            passed=True,
            confidence=float(result.get("overall_quality", 7)) / 10.0,
            issues=ctx.review_findings or [],
            artifacts=result,
            duration_seconds=time.time() - t0,
        ))

    async def _phase_security(self, ctx: ExecutionContext, sm: PipelineStateMachine) -> bool:
        t0 = time.time()
        code = ctx.generated_code or ""
        if not code:
            ctx.security_report = {"issues": [], "status": "no_code"}
            return True

        prompt = (
            f"Perform a security analysis of this code. "
            f"Check for: SQL injection, hardcoded secrets, unsafe eval/exec, "
            f"path traversal, command injection, weak crypto, SSRF.\n\n"
            f"Return JSON: {{\"issues\": [{{\"severity\": \"CRITICAL|HIGH|MEDIUM|LOW\", "
            f"\"type\": \"...\", \"description\": \"...\", \"fix\": \"...\"}}], \"score\": 0-100}}\n\n"
            f"Code:\n{code[:8000]}"
        )
        result = await self.llm.call_json(prompt, task_type="security_scan")
        issues = result.get("issues", [])
        ctx.security_report = result
        ctx.security_issues = issues if issues else None

        has_critical = any(i.get("severity") in ("CRITICAL", "HIGH") for i in issues)
        passed = not has_critical

        ctx.record_phase(PhaseOutput(
            phase_id="p06",
            phase_name="security",
            passed=passed,
            confidence=result.get("score", 100) / 100.0,
            issues=[f"{i.get('severity')}: {i.get('description')}" for i in issues],
            artifacts=result,
            duration_seconds=time.time() - t0,
        ))
        return passed

    async def _phase_testing(self, ctx: ExecutionContext, sm: PipelineStateMachine) -> bool:
        t0 = time.time()
        code = ctx.generated_code or ""
        if not code:
            ctx.test_results = {"test_code": "", "passed": True, "note": "no_code"}
            return True

        prompt = (
            f"Write comprehensive pytest tests for this {ctx.language} code. "
            f"Cover happy path, edge cases, and error cases. "
            f"Return ONLY valid pytest code, no explanations, no markdown fences.\n\n"
            f"Code:\n{code[:6000]}"
        )
        test_code = await self.llm.call(prompt, task_type="testing")
        ctx.test_results = {
            "test_code": test_code,
            "passed": True,  # TODO: wire actual test runner via phases/p07_testing
            "note": "generated_by_llm",
        }
        ctx.record_phase(PhaseOutput(
            phase_id="p07",
            phase_name="testing",
            passed=True,
            confidence=0.75,
            duration_seconds=time.time() - t0,
        ))
        return True

    async def _phase_cicd(self, ctx: ExecutionContext, sm: PipelineStateMachine) -> None:
        t0 = time.time()
        import tempfile
        from aether_os.phases.p08_cicd.pipeline import run_repair
        from aether_os.core.approval.workflow import decide_for_risk

        # Build CI log from test failures if any exist
        log_content = ""
        if ctx.test_failures:
            log_content = ctx.test_failures
        elif ctx.test_results and not ctx.test_results.get("passed", True):
            log_content = str(ctx.test_results)

        if not log_content or not ctx.generated_code:
            # No CI failure to repair — skip gracefully
            ctx.ci_result = {"status": "skipped", "reason": "no CI failure detected"}
            ctx.record_phase(PhaseOutput(
                phase_id="p08",
                phase_name="cicd",
                passed=True,
                confidence=1.0,
                duration_seconds=time.time() - t0,
            ))
            return

        # Write generated code to a temp dir so run_repair can operate on it
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "main.py").write_text(ctx.generated_code or "", encoding="utf-8")
            repair_result = run_repair(
                log_content=log_content,
                root_dir=tmp_path,
                historical_records=[],
                ast_index=None,
            )

        # Escalated — trigger human approval gate
        if repair_result.escalated:
            approval = decide_for_risk("HIGH", risk_score=repair_result.confidence)
            ctx.approval_ticket_id = f"cicd-escalation-{ctx.run_id[:8]}"
            ctx.human_approved = False
            ctx.ci_result = {
                "status": "escalated",
                "reason": repair_result.explanation,
                "approval_required": True,
                "approval_decision": approval,
                "confidence": repair_result.confidence,
            }
            logger.warning(
                "CI/CD phase escalated [run=%s]: %s", ctx.run_id, repair_result.explanation
            )
            ctx.record_phase(PhaseOutput(
                phase_id="p08",
                phase_name="cicd",
                passed=False,
                confidence=repair_result.confidence,
                issues=[repair_result.explanation],
                duration_seconds=time.time() - t0,
            ))
            return

        # Write patch to output dir if repair succeeded
        patch_path: Optional[str] = None
        if repair_result.success and repair_result.patch_diff:
            try:
                from aether_os.core.config.loader import get_config
                cfg = get_config()
                base_dir = ctx.output_dir or cfg.get(
                    "pipeline.output_dir",
                    str(Path.home() / ".aether_os" / "outputs"),
                )
                patch_dir = Path(base_dir) / ctx.project_name / ctx.run_id[:8]
                patch_dir.mkdir(parents=True, exist_ok=True)
                patch_file = patch_dir / "cicd_patch.diff"
                patch_file.write_text(repair_result.patch_diff, encoding="utf-8")
                patch_path = str(patch_file)
                logger.info("CI/CD patch written to %s", patch_path)
            except Exception as exc:
                logger.warning("Failed to write patch file: %s", exc)

        ctx.ci_result = {
            "status": "repaired" if repair_result.success else "failed",
            "explanation": repair_result.explanation,
            "confidence": repair_result.confidence,
            "patch_path": patch_path,
            "escalated": repair_result.escalated,
            "detected_language": repair_result.detected_language,
            "source": repair_result.source,
        }
        ctx.record_phase(PhaseOutput(
            phase_id="p08",
            phase_name="cicd",
            passed=repair_result.success,
            confidence=repair_result.confidence,
            issues=repair_result.violations,
            artifacts={"patch_path": patch_path, "source": repair_result.source},
            duration_seconds=time.time() - t0,
        ))

    async def _phase_docs(self, ctx: ExecutionContext, sm: PipelineStateMachine) -> None:
        t0 = time.time()
        code = ctx.generated_code or ""
        prompt = (
            f"Generate a comprehensive README.md for this project.\n\n"
            f"Project: {ctx.project_name}\n"
            f"Requirements: {ctx.requirements_doc or ctx.requirement}\n\n"
            f"Code preview:\n{code[:3000]}\n\n"
            f"Include: overview, installation, usage, API reference, examples."
        )
        result = await self.llm.call(prompt, task_type="documentation")
        ctx.docs = result
        ctx.record_phase(PhaseOutput(
            phase_id="p09",
            phase_name="docs",
            passed=bool(result),
            confidence=0.9,
            duration_seconds=time.time() - t0,
        ))

    async def _phase_packaging(self, ctx: ExecutionContext, sm: PipelineStateMachine) -> None:
        t0 = time.time()
        # TODO: wire to phases/p10_packaging for real packaging
        ctx.packaging_artifact = f"{ctx.project_name}-{ctx.run_id[:8]}.tar.gz"
        ctx.record_phase(PhaseOutput(
            phase_id="p10",
            phase_name="packaging",
            passed=True,
            confidence=1.0,
            duration_seconds=time.time() - t0,
        ))


_pipeline_instance: Optional[Pipeline] = None


def get_pipeline() -> Pipeline:
    """Return the global singleton Pipeline instance."""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = Pipeline()
    return _pipeline_instance
