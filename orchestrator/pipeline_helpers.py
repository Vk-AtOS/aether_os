"""
AetherOS — Pipeline Phase Helpers
===================================
Phase implementation methods extracted from Pipeline to keep pipeline.py
under the 600-line limit.
Each function is an async implementation for one pipeline phase.
They are bound to Pipeline as methods via import in pipeline.py.
"""
from __future__ import annotations
import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Optional
from aether_os.core.approval.workflow import decide_for_risk
from aether_os.core.config.loader import get_config
from aether_os.core.memory.fingerprinter import fingerprint
from aether_os.core.memory.store import get_memory_store
from aether_os.core.projects import get_project_manager
from aether_os.orchestrator.context import PhaseOutput
from aether_os.orchestrator.messages import PhaseInput
from aether_os.phases.p07_testing.task_agent import run as _test_run
from aether_os.phases.p08_cicd.pipeline import run_repair
import tarfile
import tempfile
logger = logging.getLogger(__name__)
async def write_output_to_disk(ctx: Any) -> str:
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
    cfg = get_config()
    base_dir = ctx.output_dir or cfg.get(
        "pipeline.output_dir",
        str(Path.home() / ".aether_os" / "outputs"),
    )
    project_dir = Path(base_dir) / ctx.project_name / ctx.run_id[:8]
    project_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    if ctx.generated_code:
        code_file = project_dir / "main.py"
        code_file.write_text(ctx.generated_code, encoding="utf-8")
        written.append(str(code_file))
    if ctx.docs:
        docs_file = project_dir / "README.md"
        docs_file.write_text(ctx.docs, encoding="utf-8")
        written.append(str(docs_file))
    if ctx.test_results and ctx.test_results.get("test_code"):
        test_dir = project_dir / "tests"
        test_dir.mkdir(exist_ok=True)
        test_file = test_dir / "test_main.py"
        test_file.write_text(ctx.test_results["test_code"], encoding="utf-8")
        written.append(str(test_file))
    if ctx.requirements_doc:
        req_file = project_dir / "REQUIREMENTS.md"
        req_file.write_text(ctx.requirements_doc, encoding="utf-8")
        written.append(str(req_file))
    if ctx.architecture_doc:
        arch_file = project_dir / "ARCHITECTURE.md"
        arch_file.write_text(ctx.architecture_doc, encoding="utf-8")
        written.append(str(arch_file))
    ctx.metadata["output_dir"] = str(project_dir)
    ctx.metadata["written_files"] = written
    logger.info("Output written to %s (%d files)", project_dir, len(written))
    return str(project_dir)
# ── Phase implementations ───────────────────────────────────────────────────
# These are standalone async functions; Pipeline binds them as instance methods.
async def phase_requirements(self: Any, ctx: Any, sm: Any) -> None:
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
async def phase_architecture(self: Any, ctx: Any, sm: Any) -> None:
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
async def phase_scaffolding(self: Any, ctx: Any, sm: Any) -> None:
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
async def phase_codegen(self: Any, ctx: Any, sm: Any, retries: int = 0) -> None:
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
    memory_context = ""
    try:
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
        phase_id="p04_backend",
        phase_name="codegen",
        passed=bool(result),
        confidence=0.85 if result else 0.0,
        duration_seconds=time.time() - t0,
    ))
async def phase_review(self: Any, ctx: Any, sm: Any) -> None:
    t0 = time.time()
    code = ctx.generated_code or ""
    prompt = (
        f"Review this {ctx.language} code for bugs, style issues, and correctness. "
        f"Return a JSON with 'findings' (list of issues) and 'overall_quality' (0-10).\n\n"
        f"Code:\n{code[:8000]}"
    )
    result = await self.llm.call_json(prompt, task_type="code_generation")
    ctx.review_findings = result.get("findings", [])
    quality_score = float(result.get("overall_quality", 7))
    review_passed = quality_score >= 5.0
    ctx.record_phase(PhaseOutput(
        phase_id="p05_frontend",
        phase_name="review",
        passed=review_passed,
        confidence=quality_score / 10.0,
        issues=ctx.review_findings or [],
        artifacts=result,
        duration_seconds=time.time() - t0,
    ))
async def phase_security(self: Any, ctx: Any, sm: Any) -> bool:
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
        phase_id="p06_review_security",
        phase_name="security",
        passed=passed,
        confidence=result.get("score", 100) / 100.0,
        issues=[f"{i.get('severity')}: {i.get('description')}" for i in issues],
        artifacts=result,
        duration_seconds=time.time() - t0,
    ))
    return passed
async def phase_testing(self: Any, ctx: Any, sm: Any) -> bool:
    t0 = time.time()
    code = ctx.generated_code or ""
    if not code:
        ctx.test_results = {"test_code": "", "passed": True, "note": "no_code"}
        return True
    passed = False
    try:
        phase_input = PhaseInput(
            run_id=ctx.run_id,
            project_id=ctx.run_id,
            phase="p07_testing",
            input_data={
                "generated_code": code,
                "language": ctx.language,
                "project_name": ctx.project_name,
            },
            output_dir=str(Path.home() / ".aether_os" / "projects" / ctx.run_id / "p07_testing"),
            domain=ctx.domain,
            client_id=ctx.run_id,
        )
        output_dir = get_project_manager().get_output_dir(ctx.run_id, "p07_testing")
        result = await asyncio.wait_for(
            _test_run(phase_input, [], output_dir), timeout=300.0
        )
        passed = result.success
        ctx.test_results = {
            "output_path": result.output_path,
            "passed": passed,
            "confidence": result.confidence,
            "metadata": result.metadata,
            "note": "executed_via_p07",
        }
        if not passed and result.issues:
            ctx.test_failures = "; ".join(result.issues[:10])
    except Exception as exc:
        logger.warning("p07_testing runner failed (%s) — marking as failed", exc)
        ctx.test_results = {"passed": False, "note": f"runner_error:{exc}"}
        passed = False
    ctx.record_phase(PhaseOutput(
        phase_id="p07_testing",
        phase_name="testing",
        passed=passed,
        confidence=ctx.test_results.get("confidence", 0.75),
        duration_seconds=time.time() - t0,
    ))
    return passed
async def phase_cicd(self: Any, ctx: Any, sm: Any) -> None:
    t0 = time.time()
    log_content = ""
    if ctx.test_failures:
        log_content = ctx.test_failures
    elif ctx.test_results and not ctx.test_results.get("passed", True):
        log_content = str(ctx.test_results)
    if not log_content or not ctx.generated_code:
        ctx.ci_result = {"status": "skipped", "reason": "no CI failure detected"}
        ctx.record_phase(PhaseOutput(
            phase_id="p08_cicd_deployment",
            phase_name="cicd",
            passed=True,
            confidence=1.0,
            duration_seconds=time.time() - t0,
        ))
        return
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "main.py").write_text(ctx.generated_code or "", encoding="utf-8")
        repair_result = run_repair(
            log_content=log_content,
            root_dir=tmp_path,
            historical_records=[],
            ast_index=None,
        )
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
        logger.warning("CI/CD phase escalated [run=%s]: %s", ctx.run_id, repair_result.explanation)
        ctx.record_phase(PhaseOutput(
            phase_id="p08_cicd_deployment",
            phase_name="cicd",
            passed=False,
            confidence=repair_result.confidence,
            issues=[repair_result.explanation],
            duration_seconds=time.time() - t0,
        ))
        return
    patch_path: Optional[str] = None
    if repair_result.success and repair_result.patch_diff:
        try:
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
        phase_id="p08_cicd_deployment",
        phase_name="cicd",
        passed=repair_result.success,
        confidence=repair_result.confidence,
        issues=repair_result.violations,
        artifacts={"patch_path": patch_path, "source": repair_result.source},
        duration_seconds=time.time() - t0,
    ))
async def phase_docs(self: Any, ctx: Any, sm: Any) -> None:
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
        phase_id="p10_docs_delivery",
        phase_name="docs_delivery",
        passed=bool(result),
        confidence=0.9,
        duration_seconds=time.time() - t0,
    ))
async def phase_observability(self: Any, ctx: Any, sm: Any) -> None:
    t0 = time.time()
    prompt = (
        f"Generate an observability configuration for this project.\n\n"
        f"Project: {ctx.project_name}\n"
        f"Tech stack: {ctx.language}\n\n"
        f"Produce a JSON with:\n"
        f"- 'health_check_endpoint': suggested /health path\n"
        f"- 'metrics': list of key metrics to track\n"
        f"- 'log_format': suggested logging format\n"
        f"- 'alerts': list of alert rules (name, condition, severity)\n"
        f"- 'dashboards': list of recommended dashboard panels\n"
    )
    try:
        result = await self.llm.call_json(prompt, task_type="documentation")
    except Exception as exc:
        logger.warning("Observability LLM call failed, using defaults: %s", exc)
        result = {
            "health_check_endpoint": "/health",
            "metrics": ["request_count", "error_rate", "latency_p95"],
            "log_format": "json",
            "alerts": [{"name": "high_error_rate", "condition": "error_rate > 5%", "severity": "warning"}],
            "dashboards": ["Overview", "Errors", "Performance"],
        }
    ctx.observability_config = result
    ctx.record_phase(PhaseOutput(
        phase_id="p09_observability",
        phase_name="observability",
        passed=True,
        confidence=0.85,
        artifacts=result,
        duration_seconds=time.time() - t0,
    ))
async def phase_packaging(self: Any, ctx: Any, sm: Any) -> None:
    t0 = time.time()
    artifact_name = f"{ctx.project_name}-{ctx.run_id[:8]}.tar.gz"
    ctx.packaging_artifact = artifact_name
    artifact_path: Optional[str] = None
    issues: list = []
    try:
        cfg = get_config()
        base_dir = ctx.output_dir or cfg.get(
            "pipeline.output_dir",
            str(Path.home() / ".aether_os" / "outputs"),
        )
        project_dir = Path(base_dir) / ctx.project_name / ctx.run_id[:8]
        if project_dir.exists():
            tar_path = project_dir.parent / artifact_name
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(project_dir, arcname=ctx.project_name)
            artifact_path = str(tar_path)
            logger.info(
                "Packaging: created artifact %s (%d bytes)",
                tar_path, tar_path.stat().st_size,
            )
        else:
            issues.append(f"Project dir not found: {project_dir}")
            logger.warning("Packaging: project dir not found — skipping tar.gz creation")
    except Exception as exc:
        issues.append(f"Packaging failed: {exc}")
        logger.warning("Packaging: tar.gz creation failed: %s", exc)
    ctx.record_phase(PhaseOutput(
        phase_id="p11_deployment",
        phase_name="packaging",
        passed=artifact_path is not None,
        confidence=1.0 if artifact_path else 0.5,
        issues=issues,
        artifacts={"artifact_path": artifact_path} if artifact_path else {},
        duration_seconds=time.time() - t0,
    ))