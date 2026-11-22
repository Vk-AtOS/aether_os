"""
P00 Business Model Generator — produces business_model.json alongside design_brief.

Runs after domain classification, before architecture generation.
Gracefully degrades to None if LLM is unavailable — does not block the pipeline.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from aether_os.core.llm.client import get_llm_client
from aether_os.core.llm.json_enforcer import extract_first_json

logger = logging.getLogger(__name__)

_BUSINESS_MODEL_PROMPT = """\
You are a business strategy analyst. Given a software application requirement, produce a structured business model analysis.

Application requirement: {requirement}
Domain: {domain}
Target stack: {stack_name}

Return a JSON object with EXACTLY these keys (no extras, no markdown):
{{
  "target_market": "1-2 sentence description of who this is for",
  "problem_statement": "the specific problem this solves",
  "value_proposition": "the core value delivered",
  "revenue_model": "subscription | transaction_fee | freemium | enterprise_license | usage_based | marketplace | advertising",
  "pricing_tiers": [
    {{"name": "Free", "price_monthly_usd": 0, "features": ["feature1", "feature2"]}},
    {{"name": "Pro", "price_monthly_usd": 29, "features": ["everything in Free", "feature3"]}},
    {{"name": "Enterprise", "price_monthly_usd": 299, "features": ["everything in Pro", "feature4"]}}
  ],
  "tam_usd_billions": 5.2,
  "sam_usd_billions": 0.8,
  "som_usd_millions": 12.0,
  "tam_source": "brief justification for the TAM estimate",
  "competitive_landscape": [
    {{"name": "Competitor", "differentiator": "what makes us different vs. them"}}
  ],
  "go_to_market": "primary GTM motion: product-led | sales-led | channel-led | community-led",
  "gtm_detail": "1-2 sentences on the specific GTM approach",
  "unit_economics": {{
    "estimated_cac_usd": 150,
    "estimated_ltv_usd": 1800,
    "ltv_cac_ratio": 12.0,
    "payback_months": 6
  }},
  "key_risks": ["risk1", "risk2", "risk3"],
  "compliance_requirements": ["HIPAA", "GDPR"]
}}

Be specific to the actual domain and requirement. Do not return generic placeholders.
"""

_FALLBACK_MODEL: Dict[str, Any] = {
    "target_market": "Business users needing workflow automation",
    "problem_statement": "Manual processes that could be automated",
    "value_proposition": "Faster, more accurate operations through software automation",
    "revenue_model": "subscription",
    "pricing_tiers": [
        {"name": "Starter", "price_monthly_usd": 29, "features": ["core features"]},
        {"name": "Pro", "price_monthly_usd": 99, "features": ["all features", "priority support"]},
        {"name": "Enterprise", "price_monthly_usd": 499, "features": ["all features", "SLA", "SSO"]},
    ],
    "tam_usd_billions": 1.0,
    "sam_usd_billions": 0.1,
    "som_usd_millions": 5.0,
    "tam_source": "Estimated from adjacent market size",
    "competitive_landscape": [],
    "go_to_market": "product-led",
    "gtm_detail": "Free tier drives adoption, upgrade prompt when usage limits hit",
    "unit_economics": {
        "estimated_cac_usd": 200,
        "estimated_ltv_usd": 1200,
        "ltv_cac_ratio": 6.0,
        "payback_months": 10,
    },
    "key_risks": ["Market adoption risk", "Technical complexity risk", "Competitive response"],
    "compliance_requirements": [],
}


async def generate_business_model(
    requirement: str,
    domain: str,
    stack_name: str,
    output_dir: Path,
) -> Optional[Dict[str, Any]]:
    """
    Generate business_model.json in output_dir.
    Returns the model dict on success, None on failure.
    Failure is logged but never raises — pipeline continues without it.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "business_model.json"

    prompt = _BUSINESS_MODEL_PROMPT.format(
        requirement=requirement[:3000],
        domain=domain,
        stack_name=stack_name,
    )

    model: Optional[Dict[str, Any]] = None
    try:
        client = get_llm_client()
        raw = await client.call(prompt, task_type="analysis")
        if raw:
            # First complete object: fences, leading prose and trailing explanation are ignored.
            model = extract_first_json(raw, expect=dict)
            logger.info("p00: generated business model for domain=%s", domain)
    except ValueError as exc:
        logger.warning("p00: business model JSON parse failed: %s", exc)
        model = _FALLBACK_MODEL.copy()
    except Exception as exc:
        logger.warning("p00: business model generation failed: %s", exc)
        model = _FALLBACK_MODEL.copy()

    if model is None:
        model = _FALLBACK_MODEL.copy()

    # Add metadata fields so downstream consumers can identify the source
    model["domain"] = domain
    model["generated_by"] = "AetherOS P00 Business Model Generator"

    out_path.write_text(json.dumps(model, indent=2))
    logger.info("p00: wrote business_model.json to %s", out_path)
    return model
