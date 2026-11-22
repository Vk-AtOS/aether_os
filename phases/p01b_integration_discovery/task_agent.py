"""P01b Integration Discovery — identify external systems the app needs to connect to.

Makes one LLM call that outputs a JSON list of required integrations:
  {
    "integrations": [
      {
        "name": "Stripe",
        "type": "payment_processor",
        "auth_method": "api_key",
        "endpoints_needed": ["create_payment_intent", "webhook_handler"],
        "sync_direction": "outbound"
      }
    ]
  }

Stored as integration_map.json; returned in TaskResult.data so it flows into
accumulated_context["integration_map"] for p04c_integration_codegen to use.
"""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

_INTEGRATION_CATEGORIES = """
- Payment processors: Stripe, PayPal, Braintree, Square, Razorpay
- CRM: Salesforce, HubSpot, Zoho CRM
- ERP: SAP, Oracle, Microsoft Dynamics
- Identity providers / SSO: Okta, Auth0, Active Directory, Azure AD, Google Workspace
- Cloud storage: Amazon S3, Google Cloud Storage, Azure Blob, Cloudinary
- Communication: SendGrid (email), Mailgun, Twilio (SMS/voice), Slack, Discord
- Accounting: QuickBooks, Xero, FreshBooks
- E-commerce: Shopify, WooCommerce
- Analytics: Mixpanel, Segment, Amplitude, PostHog
- Maps / location: Google Maps, Mapbox
- Search: Elasticsearch, Algolia
- File conversion: Puppeteer, LibreOffice (PDF), FFmpeg (video)
- Shipping / logistics: FedEx, UPS, Shippo
- Background jobs: Celery, Dramatiq, RQ
"""


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """Discover integrations from the project description via one LLM call."""
    output_dir.mkdir(parents=True, exist_ok=True)

    data: dict = getattr(phase_input, "input_data", {}) or {}
    raw_input = data.get("raw_input", "")
    domain = data.get("domain", "general")
    project_name = data.get("project_name", "App")

    if not raw_input:
        logger.info("p01b: no raw_input — skipping integration discovery")
        result_data = {"integrations": [], "skipped": True, "reason": "no project description"}
        out_path = output_dir / "integration_map.json"
        out_path.write_text(json.dumps(result_data, indent=2))
        return TaskResult(
            output_path=str(out_path),
            confidence=0.5,
            metadata={"integration_map": result_data, "skipped": True},
            success=True,
        )

    integration_map: dict = {"integrations": []}

    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()

        prompt = f"""\
Analyze this project description and identify which external systems or APIs the application \
needs to integrate with.

Project: {project_name}
Domain: {domain}
Description: {raw_input[:3000]}

Consider these integration categories:
{_INTEGRATION_CATEGORIES}

Only include integrations that are clearly implied by the project description. \
Do NOT invent integrations that are not needed.

Output JSON (only JSON, no explanation):
{{
  "integrations": [
    {{
      "name": "Stripe",
      "type": "payment_processor",
      "auth_method": "api_key",
      "endpoints_needed": ["create_payment_intent", "list_charges", "create_refund", "webhook_handler"],
      "sync_direction": "outbound",
      "priority": "required"
    }}
  ]
}}

Fields:
- name: official name of the integration
- type: category (payment_processor, crm, erp, identity_provider, cloud_storage, communication, accounting, etc.)
- auth_method: api_key | oauth2 | basic_auth | webhook_secret | service_account
- endpoints_needed: list of specific API operations needed
- sync_direction: inbound | outbound | bidirectional
- priority: required | recommended | optional

Return ONLY the JSON object. No markdown fences."""

        result = await llm.call(prompt, task_type="analysis")
        if result:
            result = re.sub(r"^```(?:json)?\s*\n?", "", result.strip())
            result = re.sub(r"\n?```\s*$", "", result.strip())
            parsed = json.loads(result)
            if isinstance(parsed, dict) and "integrations" in parsed:
                integration_map = parsed
                logger.info(
                    "p01b: discovered %d integrations for %s",
                    len(parsed["integrations"]), project_name,
                )
    except Exception as exc:
        logger.warning("p01b: LLM integration discovery failed: %s", exc)
        integration_map = {"integrations": [], "error": str(exc)}

    out_path = output_dir / "integration_map.json"
    out_path.write_text(json.dumps(integration_map, indent=2))
    logger.info("p01b: integration_map.json written to %s", out_path)

    return TaskResult(
        output_path=str(out_path),
        confidence=0.85,
        metadata={
            "integration_map": integration_map,
            "integrations_count": len(integration_map.get("integrations", [])),
        },
        success=True,
    )
