"""
End-to-end repair orchestrator for the AetherOS CI/CD phase.

Connects log parsing, localization, fingerprinting, matching,
and stability verification into a single repair pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from aether_os.phases.p08_cicd.dfle.call_graph import CallGraph
from aether_os.phases.p08_cicd.dfle.log_parser import parse_log
from aether_os.phases.p08_cicd.dfle.localizer import localize
from aether_os.phases.p08_cicd.patch_reuse.fingerprint import build_fingerprint
from aether_os.phases.p08_cicd.patch_reuse.matcher import match
from aether_os.phases.p08_cicd.dsee.boundary import check_boundary
from aether_os.phases.p08_cicd.dsee.impact import simulate_impact, ImpactResult
from aether_os.phases.p08_cicd.dsee.test_runner import TieredTestRunner

logger = logging.getLogger(__name__)
from aether_os.phases.p08_cicd.dsee.verifier import verify_stability
from aether_os.phases.p08_cicd.lang import detect_language_adapter
from aether_os.phases.p08_cicd.feedback import fingerprint as log_fingerprint, GLOBAL_REPAIR_MEMORY
from aether_os.phases.p08_cicd.slm.prompts import PromptTemplates
from aether_os.phases.p08_cicd.slm.validator import PatchValidator
from aether_os.phases.p08_cicd.sandbox.docker import (
    validate_patch_in_sandbox,
    is_sandbox_available
)


@dataclass
class RepairResult:
    """Result of the end-to-end repair process."""

    success: bool
    confidence: float
    patch_diff: str
    explanation: str
    escalated: bool
    violations: list[str] = field(default_factory=list)
    slm_generated: bool = False
    detected_language: str = "unknown"
    source: str = "slm" # "slm" or "memory"
    fingerprint: str = ""
    error_type: str = ""
    sandbox_validated: bool = False
    sandbox_result: Optional[str] = None
    # "passed", "failed", "skipped"


def score_confidence(
    match_confidence: float,
    candidate_confidence: float,
    boundary_passed: bool,
    impact_result: ImpactResult,
    tier1_passed: bool,
    tier2_passed: bool,
) -> float:
    """
    Weighted score combining multiple factors for final repair confidence.
    """
    # 1. Match confidence: 0.35 weight
    s1 = match_confidence * 0.35

    # 2. Candidate confidence (from localizer): 0.25 weight
    s2 = candidate_confidence * 0.25

    # 3. Boundary passed (1.0 if True else 0.0): 0.15 weight
    s3 = (1.0 if boundary_passed else 0.0) * 0.15

    # 4. Impact safe + risk_level safe (1.0/0.5/0.0): 0.15 weight
    impact_score = 0.0
    if impact_result.safe:
        if impact_result.risk_level == "safe":
            impact_score = 1.0
        elif impact_result.risk_level == "minor":
            impact_score = 0.5
    s4 = impact_score * 0.15

    # 5. Tier 1 + Tier 2 both passed (1.0 if both else 0.0): 0.10 weight
    s5 = (1.0 if (tier1_passed and tier2_passed) else 0.0) * 0.10

    return round(s1 + s2 + s3 + s4 + s5, 4)


def run_repair(
    log_content: str,
    root_dir: str | Path,
    historical_records: list[dict[str, Any]],
    ast_index: Any,
    call_graph: CallGraph | None = None,
) -> RepairResult:
    """
    Orchestrate the end-to-end repair pipeline.

    Args:
        log_content: Raw CI log content.
        root_dir: Path to the repository root.
        historical_records: List of historical patch records for matching.
        ast_index: Current AST index.
        call_graph: Current CallGraph object.

    Returns:
        RepairResult indicating success and providing the patch if found.
    """
    # Handle None call_graph safely
    if call_graph is None:
        call_graph = CallGraph()

    # Fingerprint and Memory Lookup (Batch 12)
    fp = log_fingerprint(log_content)
    stored = GLOBAL_REPAIR_MEMORY.lookup(fp)
    # Extract repo_name from root_dir for recording later
    repo_name = Path(root_dir).name

    if stored and stored.get("success_count", 0) >= 2:
        # Resolve language for early return
        lang_adapter = detect_language_adapter(log_content)
        detected_lang = lang_adapter.language_name if lang_adapter else "unknown"
        
        return RepairResult(
            success=True,
            confidence=min(stored["confidence"] + 0.05, 1.0),
            patch_diff=stored["patch_diff"],
            explanation=f"Reused known fix (seen {stored['success_count']} times)",
            escalated=False,
            source="memory",
            fingerprint=fp,
            detected_language=detected_lang
        )

    # 1. Parse CI log
    parsed_log = parse_log(log_content)
    
    # Language detection
    lang_adapter = detect_language_adapter(log_content)
    detected_lang = lang_adapter.language_name if lang_adapter else "unknown"

    # Extract error type for prompting
    error_type = "Unknown"
    if parsed_log.stack_traces:
        error_type = parsed_log.stack_traces[0].exception_type

    if not parsed_log.stack_traces:
        res = RepairResult(
            success=False,
            confidence=0.0,
            patch_diff="",
            explanation="No stack traces found in CI log.",
            escalated=True,
            detected_language=detected_lang,
            fingerprint=fp,
            error_type=error_type
        )
        GLOBAL_REPAIR_MEMORY.record_failure(fp)
        return res

    # 2. Localize root cause
    candidates = localize(parsed_log, call_graph)
    if not candidates:
        res = RepairResult(
            success=False,
            confidence=0.0,
            patch_diff="",
            explanation="Failed to localize root cause from stack traces.",
            escalated=True,
            detected_language=detected_lang,
            fingerprint=fp,
            error_type=error_type
        )
        GLOBAL_REPAIR_MEMORY.record_failure(fp)
        return res

    top_candidate = candidates[0]

    # 3. Build fingerprint
    fingerprint = build_fingerprint(top_candidate, parsed_log)

    # 4. Match known patch
    match_res = match(fingerprint, historical_records)

    # 5. Identify patch to verify (Match or SLM)
    patch_diff = ""
    slm_generated = False
    base_confidence = 0.0

    if match_res.matched:
        patch_diff = match_res.patch_diff
        base_confidence = match_res.confidence
    else:
        # Attempt SLM repair
        from aether_os.phases.p08_cicd.slm import OllamaClient
        
        # Get target file content
        file_content = ""
        target_file = top_candidate.target_file
        full_path = Path(root_dir) / target_file
        if full_path.exists():
            file_content = full_path.read_text()

        # Build prompt using templates
        system, user = PromptTemplates.build_prompt(
            error_type, log_content, file_content, target_file
        )
        
        ollama = OllamaClient()
        response = ollama.generate_patch(system, user)
        
        if response:
            # Extract and validate diff
            validator = PatchValidator()
            extracted = validator.extract_diff(response)
            
            if extracted and validator.is_valid_diff(extracted):
                patch_diff = extracted
                slm_generated = True
                base_confidence = 0.7
            else:
                res = RepairResult(
                    success=False,
                    confidence=0.0,
                    patch_diff="",
                    explanation="SLM generated an invalid patch format.",
                    escalated=True,
                    detected_language=detected_lang,
                    fingerprint=fp,
                    error_type=error_type
                )
                GLOBAL_REPAIR_MEMORY.record_failure(fp)
                return res
        else:
            res = RepairResult(
                success=False,
                confidence=0.0,
                patch_diff="",
                explanation=f"No matching patch found and SLM failed to generate one.",
                escalated=True,
                detected_language=detected_lang,
                fingerprint=fp,
                error_type=error_type
            )
            GLOBAL_REPAIR_MEMORY.record_failure(fp)
            return res

    # 6. Run DSEE verification steps
    target_file = top_candidate.target_file

    # Boundary check
    boundary_res = check_boundary(patch_diff, target_file)
    if not boundary_res.passed:
        # If SLM failed DSEE, we escalate
        if slm_generated:
            res = RepairResult(
                success=False,
                confidence=0.0,
                patch_diff="",
                explanation="SLM-generated patch failed boundary enforcement.",
                escalated=True,
                violations=boundary_res.violations,
                detected_language=detected_lang,
                fingerprint=fp
            )
            GLOBAL_REPAIR_MEMORY.record_failure(fp)
            return res
        
        res = RepairResult(
            success=False,
            confidence=base_confidence,
            patch_diff=patch_diff,
            explanation="Patch failed boundary enforcement.",
            escalated=False,
            violations=boundary_res.violations,
            detected_language=detected_lang,
            fingerprint=fp
        )
        GLOBAL_REPAIR_MEMORY.record_failure(fp)
        return res

    # Impact simulation
    impact_res = simulate_impact(patch_diff, ast_index, call_graph)

    # Test execution
    test_runner = TieredTestRunner(root_dir)
    
    # Identify specific failing test name from parsed log if possible
    test_name = parsed_log.test_names[0] if parsed_log.test_names else ""
    
    # Tier 1: specific failing test
    t1_res = test_runner.run_tier1(test_name)
    if not t1_res.passed:
        if slm_generated:
            res = RepairResult(
                success=False,
                confidence=0.0,
                patch_diff="",
                explanation="SLM-generated patch failed Tier 1 test execution.",
                escalated=True,
                violations=[f"Tier 1 failure: {t1_res.output[:200]}..."],
                detected_language=detected_lang,
                fingerprint=fp
            )
            GLOBAL_REPAIR_MEMORY.record_failure(fp)
            return res
        res = RepairResult(
            success=False,
            confidence=base_confidence,
            patch_diff=patch_diff,
            explanation="Tier 1 test execution failed.",
            escalated=False,
            violations=[f"Tier 1 failure: {t1_res.output[:200]}..."],
            detected_language=detected_lang,
            fingerprint=fp
        )
        GLOBAL_REPAIR_MEMORY.record_failure(fp)
        return res

    # Tier 2: related tests
    t2_res = test_runner.run_tier2(target_file)
    if not t2_res.passed:
        if slm_generated:
            res = RepairResult(
                success=False,
                confidence=0.0,
                patch_diff="",
                explanation="SLM-generated patch failed Tier 2 test execution.",
                escalated=True,
                violations=[f"Tier 2 failure: {t2_res.output[:200]}..."],
                detected_language=detected_lang,
                fingerprint=fp
            )
            GLOBAL_REPAIR_MEMORY.record_failure(fp)
            return res
        res = RepairResult(
            success=False,
            confidence=base_confidence,
            patch_diff=patch_diff,
            explanation="Tier 2 test execution failed.",
            escalated=False,
            violations=[f"Tier 2 failure: {t2_res.output[:200]}..."],
            detected_language=detected_lang,
            fingerprint=fp
        )
        GLOBAL_REPAIR_MEMORY.record_failure(fp)
        return res

    # Stability verification
    verification_res = verify_stability(t1_res, impact_res)
    
    if not verification_res.approved:
        if slm_generated:
            res = RepairResult(
                success=False,
                confidence=0.0,
                patch_diff="",
                explanation="SLM-generated patch failed stability verification.",
                escalated=True,
                violations=verification_res.failures,
                detected_language=detected_lang,
                fingerprint=fp
            )
            GLOBAL_REPAIR_MEMORY.record_failure(fp)
            return res
        res = RepairResult(
            success=False,
            confidence=base_confidence,
            patch_diff=patch_diff,
            explanation="Stability verification failed.",
            escalated=False,
            violations=verification_res.failures,
            detected_language=detected_lang,
            fingerprint=fp
        )
        GLOBAL_REPAIR_MEMORY.record_failure(fp)
        return res

    # Compute final confidence score
    final_confidence = score_confidence(
        match_confidence=base_confidence,
        candidate_confidence=top_candidate.confidence_score,
        boundary_passed=boundary_res.passed,
        impact_result=impact_res,
        tier1_passed=t1_res.passed,
        tier2_passed=t2_res.passed,
    )

    # Success!
    explanation = f"Patch successfully verified (match type: {match_res.match_type})."
    if slm_generated:
        explanation = "Patch successfully generated by SLM and verified by DSEE."

    final_result = RepairResult(
        success=True,
        confidence=final_confidence,
        patch_diff=patch_diff,
        explanation=explanation,
        escalated=False,
        slm_generated=slm_generated,
        detected_language=detected_lang,
        fingerprint=fp,
        error_type=error_type
    )
    
    # Sandbox validation (if available)
    if final_result.patch_diff and is_sandbox_available():
        try:
            # We need the original code to validate the patch in sandbox
            # If we don't have it easily available, we skip for now or try to read it
            file_content = ""
            full_path = Path(root_dir) / top_candidate.target_file
            if full_path.exists():
                file_content = full_path.read_text()
            
            if file_content:
                sb = validate_patch_in_sandbox(
                    file_content,
                    final_result.patch_diff,
                    detected_lang or "python"
                )
                final_result.sandbox_validated = True
                final_result.sandbox_result = "passed" if sb.success else "failed"
                if not sb.success:
                    logger.warning(
                        f"Sandbox validation failed for job {fp}: {sb.stderr[:200]}"
                    )
            else:
                final_result.sandbox_validated = False
                final_result.sandbox_result = "skipped"
        except Exception as e:
            logger.warning(f"Sandbox validation error: {e}")
            final_result.sandbox_validated = False
            final_result.sandbox_result = "skipped"
    else:
        final_result.sandbox_validated = False
        final_result.sandbox_result = "skipped"

    # Record success in memory
    GLOBAL_REPAIR_MEMORY.record_success(fp, patch_diff, final_confidence, repo_name)
    
    return final_result
