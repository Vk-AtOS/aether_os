"""
Stack classifier for P00 — maps user spec text to a StackProfile.

Called at the start of P00 before screenshot analysis. The result is written
into design_brief.json as the "build_profile" key and propagated to every
downstream phase by factory_pipeline.py.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from aether_os.core.stack_profiles import (
    DEFAULT_PROFILE,
    StackProfile,
    get_profile,
    profile_to_dict,
)
from aether_os.phases.p00_research.prompts import STACK_CLASSIFIER_PROMPT

logger = logging.getLogger(__name__)


async def classify_build(spec_text: str, domain: str) -> StackProfile:
    """
    Use the LLM to classify the build spec into a StackProfile.
    Falls back to DEFAULT_PROFILE (web_saas) on any error.
    """
    if not spec_text or not spec_text.strip():
        logger.info("p00/stack_selector: empty spec — defaulting to web_saas")
        return DEFAULT_PROFILE

    prompt = STACK_CLASSIFIER_PROMPT.format(
        spec_text=spec_text[:3000],  # cap to avoid token overflow
        domain=domain,
    )

    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        raw = await llm.call_json(prompt, task_type="analysis")
        profile_name = raw.get("profile", "")
        confidence = float(raw.get("confidence", 0.0))
        reason = raw.get("reason", "")

        profile = get_profile(profile_name)
        if profile.name == DEFAULT_PROFILE.name and profile_name not in ("web_saas", ""):
            logger.warning(
                "p00/stack_selector: LLM returned unknown profile %r — using web_saas. Reason: %s",
                profile_name, reason,
            )
        else:
            logger.info(
                "p00/stack_selector: classified as %r (confidence=%.2f). Reason: %s",
                profile.name, confidence, reason,
            )
        return profile

    except Exception as e:
        logger.warning("p00/stack_selector: LLM classification failed, defaulting to web_saas: %s", e)
        return DEFAULT_PROFILE


def inject_into_brief(design_brief: dict, profile: StackProfile) -> dict:
    """Add build_profile key to design_brief dict in-place and return it."""
    design_brief["build_profile"] = profile_to_dict(profile)
    return design_brief
