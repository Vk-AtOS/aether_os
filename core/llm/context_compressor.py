"""
Context Compression Engine — reduces accumulated_context to what each phase actually needs.

Strategy:
1. Each phase declares its "interest keys" — the context fields it reads
2. Compressor extracts only those keys + always-kept fields
3. For large string values (>2000 chars), summarize to first 500 chars + "... [truncated]"
4. For list values with >20 items, truncate to 20 with a count annotation
5. Returns a lean dict sized for the LLM's context window
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Fields every phase needs regardless of phase-specific interest keys.
# These carry identity/routing information used across the whole pipeline.
_ALWAYS_KEPT_KEYS: frozenset[str] = frozenset({
    "run_id",
    "org_id",
    "project_name",
    "domain",
    "decisions",
    "architecture_warnings",
    "autonomous_mode",
    "decision_mode",
})

# Map of phase name → context keys that phase actually reads.
# Derived by grepping all phase task_agent.py / prompts.py / helpers.py files
# for .get("key") patterns and cross-referencing accumulated_context writes.
PHASE_INTEREST_KEYS: dict[str, list[str]] = {
    # ── Intake / Requirements ──────────────────────────────────────────────────
    "p00_intake": [
        "raw_input", "github_url", "existing_schema", "tech_preferences",
    ],
    "p00a_intake": [
        "raw_input", "github_url", "existing_schema", "tech_preferences",
    ],
    "p00_research": [
        "raw_input", "domain", "tech_preferences",
    ],
    "p00b_data_archaeology": [
        "raw_input", "github_url", "existing_schema", "entities",
    ],
    "p00c_architecture_planner": [
        "raw_input", "domain", "tech_preferences", "build_profile",
    ],
    "p01_requirements": [
        "raw_input", "domain", "functional_requirements", "structured_requirements",
        "tech_preferences", "build_profile", "org_id",
    ],
    "p01_intake_requirements": [
        "raw_input", "domain", "functional_requirements", "structured_requirements",
        "tech_preferences", "build_profile",
    ],
    "p01b_integration_discovery": [
        "raw_input", "domain", "functional_requirements", "integration_map",
        "p01b_integration_discovery_output",
    ],
    # ── Architecture / IR ──────────────────────────────────────────────────────
    "p02_architecture": [
        "raw_input", "domain", "functional_requirements", "structured_requirements",
        "tech_stack", "language", "build_profile", "architecture_json",
    ],
    "p02b_domain_ir": [
        "raw_input", "domain", "functional_requirements", "architecture_json",
        "existing_schema", "entities", "domain_ir_path",
    ],
    "p02c_permission_modeling": [
        "domain", "entities", "architecture_json", "permission_model",
    ],
    # ── Scaffolding ────────────────────────────────────────────────────────────
    "p03_scaffolding": [
        "domain", "project_name", "language", "tech_stack",
        "architecture_json", "build_profile",
        # Specialised sub-type keys
        "device_type", "comms", "genre", "modules",
    ],
    # ── Backend Codegen ────────────────────────────────────────────────────────
    "p04_backend": [
        "domain", "entities", "architecture_json", "domain_ir_path",
        "project_name", "backend_src_dir", "project_dir",
        "integration_map", "workflows", "requirements_doc",
        "pre_gen_warnings", "raw_input",
    ],
    "p04a_backend_codegen": [
        "domain", "entities", "architecture_json", "domain_ir_path",
        "project_name", "backend_src_dir", "project_dir",
        "integration_map", "workflows", "requirements_doc",
        "pre_gen_warnings", "raw_input", "org_id",
        "user_personas", "realtime_features", "notifications",
    ],
    "p04b_business_logic": [
        "domain", "entities", "project_name", "app_name",
        "project_dir", "backend_src_dir", "domain_ir_path",
        "domain_knowledge", "integration_map", "integration_flags",
        "workflows", "notifications", "requirements_doc", "raw_input",
        "phase_confidence", "pre_gen_warnings",
    ],
    "p04b_uiux_design": [
        "domain", "entities", "project_name", "raw_input",
        "designer_spec", "design_brief", "user_personas",
    ],
    "p04c_integration_codegen": [
        "domain", "entities", "project_name", "project_dir",
        "backend_src_dir", "integration_map", "integration_flags",
        "p01b_integration_discovery_output", "domain_knowledge",
    ],
    # ── Frontend ───────────────────────────────────────────────────────────────
    "p05_frontend": [
        "domain", "entities", "project_name", "build_profile",
        "domain_ir_path", "architecture_json", "designer_spec",
        "design_brief", "user_personas", "realtime_features",
        "has_customer_portal", "has_landing_page", "app_brand",
        "app_tagline", "autonomous_mode", "decision_mode",
        "project_dir", "services", "org_id",
    ],
    "p05b_mobile": [
        "domain", "entities", "project_name", "designer_spec", "build_profile",
    ],
    "p05c_desktop": [
        "domain", "entities", "project_name", "designer_spec", "build_profile",
    ],
    "p05d_cli": [
        "domain", "entities", "project_name", "language", "build_profile",
    ],
    # ── Review / Security ─────────────────────────────────────────────────────
    "p06_review_security": [
        "domain", "project_name", "project_dir", "backend_output_path",
        "domain_ir_path", "architecture_json", "compliance_score",
    ],
    "p06b_formal_verification": [
        "domain", "project_name", "project_dir",
    ],
    # ── Testing ───────────────────────────────────────────────────────────────
    "p07_testing": [
        "domain", "language", "project_name", "project_dir",
        "entities", "domain_ir_path",
    ],
    "p07a_unit_testing": [
        "domain", "language", "project_name", "project_dir", "entities",
    ],
    "p07b_performance_testing": [
        "domain", "project_name", "project_dir",
        "ci_failure", "test_failures",
    ],
    "p07b_self_healing": [
        "domain", "project_name", "project_dir",
        "ci_failure", "test_failures", "entities",
    ],
    "p07c_accessibility_testing": [
        "domain", "project_name", "project_dir",
    ],
    "p07d_e2e_testing": [
        "domain", "project_name", "project_dir", "entities",
        "has_customer_portal",
    ],
    # ── CI/CD / Deployment ────────────────────────────────────────────────────
    "p08_cicd": [
        "domain", "project_name", "project_dir",
        "ci_failure", "test_failures", "language", "tech_stack",
    ],
    "p08_cicd_deployment": [
        "domain", "project_name", "project_dir",
        "ci_failure", "test_failures", "language", "tech_stack",
    ],
    # ── Documentation / Observability ─────────────────────────────────────────
    "p09_documentation": [
        "domain", "project_name", "architecture_json",
        "tech_stack", "entities",
    ],
    "p09_observability": [
        "domain", "project_name", "project_dir", "architecture_json",
    ],
    # ── Delivery / Handoff ────────────────────────────────────────────────────
    "p10_docs_delivery": [
        "domain", "project_name", "architecture_json", "entities",
        "files_written",
    ],
    "p11_deployment": [
        "domain", "project_name", "project_dir", "architecture_json",
        "canonical_src_dir", "domain_ir_path",
    ],
    "p11a_monitoring": [
        "domain", "project_name", "project_dir",
    ],
    "p14_client_portal": [
        "domain", "project_name", "project_dir", "architecture_json",
        "domain_ir_path", "integration_map", "permission_model",
        "council_verdict", "quality_score", "business_model",
        "raw_input", "files_written", "tickets",
    ],
    "p15_handoff": [
        "domain", "project_name", "project_dir", "architecture_json",
        "domain_ir_path", "integration_map", "permission_model",
        "quality_score", "raw_input", "files_written",
        "frontend_build_failed",
    ],
}

# Characters over which a string value is truncated.
_STRING_TRUNCATE_CHARS = 2_000
_STRING_KEEP_CHARS = 500

# Lists longer than this are truncated.
_LIST_TRUNCATE_LEN = 20


def summarize_large_value(value: Any, max_chars: int = _STRING_KEEP_CHARS) -> Any:
    """Truncate large strings; annotate truncated lists with item count.

    - str  > _STRING_TRUNCATE_CHARS → first max_chars chars + "... [truncated N chars]"
    - list > _LIST_TRUNCATE_LEN     → first 20 items + annotation string appended
    - dict                          → recursively summarize values (shallow, one level)
    - everything else               → returned unchanged
    """
    if isinstance(value, str) and len(value) > _STRING_TRUNCATE_CHARS:
        tail = f"... [truncated {len(value) - max_chars} chars]"
        return value[:max_chars] + tail

    if isinstance(value, list) and len(value) > _LIST_TRUNCATE_LEN:
        omitted = len(value) - _LIST_TRUNCATE_LEN
        truncated: list = list(value[:_LIST_TRUNCATE_LEN])
        truncated.append(f"... [{omitted} more items omitted]")
        return truncated

    if isinstance(value, dict):
        # Shallow pass — only summarize direct string values of nested dicts
        return {k: summarize_large_value(v, max_chars) for k, v in value.items()}

    return value


def get_compression_ratio(original: dict, compressed: dict) -> float:
    """Return the char-length compression ratio (compressed / original).

    Returns 1.0 if original is empty to avoid divide-by-zero.
    Lower is better (0.3 = 70% reduction).
    """
    try:
        orig_len = len(json.dumps(original))
        comp_len = len(json.dumps(compressed))
        if orig_len == 0:
            return 1.0
        return comp_len / orig_len
    except Exception as exc:
        logger.warning("context_compressor: get_compression_ratio failed: %s", exc)
        return 1.0


def compress_context(
    phase_name: str,
    ctx: dict,
    max_chars: int = 40_000,
) -> dict:
    """Return a compressed copy of ctx containing only what phase_name reads.

    Steps:
    1. Resolve interest keys for this phase (always-kept + phase-specific).
    2. Extract only those keys from ctx.
    3. Truncate large string values and long lists.
    4. If the result still exceeds max_chars (JSON length), drop lowest-priority
       keys (phase-specific only, never always-kept) until it fits.

    Always fails open — if anything goes wrong the full ctx is returned.
    """
    try:
        phase_keys: list[str] = PHASE_INTEREST_KEYS.get(phase_name, [])
        keep_keys: set[str] = _ALWAYS_KEPT_KEYS | set(phase_keys)

        # Build compressed dict with only relevant keys
        compressed: dict = {}
        for key in keep_keys:
            if key in ctx:
                compressed[key] = summarize_large_value(ctx[key])

        # Enforce overall max_chars budget by dropping phase-specific keys first
        try:
            serialized = json.dumps(compressed)
        except Exception as exc:
            logger.warning("context_compressor: JSON serialization failed: %s", exc)
            return ctx

        if len(serialized) > max_chars:
            # Drop phase-specific keys (lowest priority) to fit budget
            # Always-kept keys are never dropped
            droppable = [k for k in phase_keys if k in compressed and k not in _ALWAYS_KEPT_KEYS]
            for key in reversed(droppable):
                del compressed[key]
                try:
                    if len(json.dumps(compressed)) <= max_chars:
                        break
                except Exception as exc:
                    logger.warning("context_compressor: size check failed: %s", exc)
                    break

        ratio = get_compression_ratio(ctx, compressed)
        logger.debug(
            "context_compressor: phase=%s keys=%d/%d ratio=%.2f",
            phase_name, len(compressed), len(ctx), ratio,
        )
        return compressed

    except Exception as exc:
        logger.warning(
            "context_compressor: compress_context failed for phase '%s' (returning full ctx): %s",
            phase_name, exc,
        )
        return ctx
