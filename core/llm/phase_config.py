"""Per-phase LLM configuration: temperature, max_tokens, preferred_model_tier.

Code generation phases use low temperature (precision over creativity).
Requirements/brainstorming phases use higher temperature (creative divergence).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PhaseLLMConfig:
    temperature: float = 0.4
    max_tokens: int = 4096
    model_tier: str = "standard"  # "cheap" | "standard" | "powerful"


# Phase-specific overrides.
# Any phase not listed here falls back to PhaseLLMConfig() defaults.
PHASE_LLM_CONFIGS: dict[str, PhaseLLMConfig] = {
    # ── Code generation: precision over creativity ────────────────────────────
    "p04a_backend_codegen": PhaseLLMConfig(temperature=0.2, max_tokens=8192, model_tier="powerful"),
    "p04b_business_logic": PhaseLLMConfig(temperature=0.2, max_tokens=4096, model_tier="standard"),
    "p04c_integration_codegen": PhaseLLMConfig(temperature=0.15, max_tokens=4096, model_tier="standard"),
    "p05_frontend": PhaseLLMConfig(temperature=0.2, max_tokens=8192, model_tier="standard"),
    # ── Architecture/domain: structured but creative ──────────────────────────
    "p02_architecture": PhaseLLMConfig(temperature=0.5, max_tokens=4096, model_tier="powerful"),
    "p02b_domain_ir": PhaseLLMConfig(temperature=0.3, max_tokens=4096, model_tier="powerful"),
    # ── Requirements/brainstorming: highest creativity ────────────────────────
    "p01_intake_requirements": PhaseLLMConfig(temperature=0.7, max_tokens=2048, model_tier="standard"),
    "p00_research": PhaseLLMConfig(temperature=0.6, max_tokens=2048, model_tier="cheap"),
    # ── Boilerplate phases: cheap model, minimal creativity needed ────────────
    "p12a_feature_flags": PhaseLLMConfig(temperature=0.1, max_tokens=1024, model_tier="cheap"),
    "p13_app_memory": PhaseLLMConfig(temperature=0.1, max_tokens=1024, model_tier="cheap"),
    # ── Security/verification: low temperature for deterministic output ───────
    "p06_review_security": PhaseLLMConfig(temperature=0.1, max_tokens=4096, model_tier="standard"),
    "p06b_formal_verification": PhaseLLMConfig(temperature=0.0, max_tokens=4096, model_tier="standard"),
}


def get_phase_config(phase_name: str) -> PhaseLLMConfig:
    """Return LLM config for a phase, falling back to sensible defaults.

    Usage in a phase task_agent::

        from core.llm.phase_config import get_phase_config
        cfg = get_phase_config("p04a_backend_codegen")
        result = await llm.call(prompt, temperature=cfg.temperature, max_tokens=cfg.max_tokens)
    """
    return PHASE_LLM_CONFIGS.get(phase_name, PhaseLLMConfig())
