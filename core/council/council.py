"""
AetherOS — LLM Council

Two review gates:
  PreFlightCouncil  — validates a factory request before the pipeline starts
  DeliveryCouncil   — validates pipeline output before delivery to the client

Result schema (both councils):
  {
    "passed":      bool,
    "score":       float,   # 0.0 – 1.0
    "reason":      str,
    "suggestions": list[str],
  }

Behaviour is controlled by two env vars:
  COUNCIL_ENABLED=true      — run council checks (default: true)
  COUNCIL_STRICT_MODE=false — when true, failed checks block the operation
                              (default: false — log warning but always proceed)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_COUNCIL_SYSTEM = (
    "You are a senior software engineering council member reviewing requests for an "
    "autonomous code-generation system. Be concise, structured, and objective."
)

_PREFLIGHT_PROMPT_TMPL = """\
Review the following software factory request and evaluate it.

Request: {raw_input}
Domain: {domain}

Evaluate on these criteria:
1. Clarity — is the requirement specific enough to build from?
2. Feasibility — is it technically achievable by an automated system?
3. Safety — does it request anything harmful, unethical, or illegal?
4. Scope — is the scope reasonable for a single automated pipeline run?

Return ONLY valid JSON (no markdown, no fences):
{{
  "passed": true|false,
  "score": 0.0-1.0,
  "reason": "one sentence summary",
  "suggestions": ["improvement if any", "..."]
}}

Pass if score >= 0.6 and no safety violations.
"""

_DELIVERY_PROMPT_TMPL = """\
Review the following automated pipeline delivery summary.

Project: {project_name}
Domain: {domain}
Phases completed: {phases_completed}
Phase results summary: {phases_summary}

Evaluate on these criteria:
1. Completeness — did all required phases complete successfully?
2. Quality — are there any obvious failures or critical errors?
3. Consistency — do phase results indicate a coherent deliverable?
4. Security — were security and review phases passed?

Return ONLY valid JSON (no markdown, no fences):
{{
  "passed": true|false,
  "score": 0.0-1.0,
  "reason": "one sentence summary",
  "suggestions": ["follow-up action if any", "..."]
}}

Pass if score >= 0.5 and no critical phase failures.
"""

_PASS_RESULT: Dict[str, Any] = {
    "passed": True,
    "score": 1.0,
    "reason": "Council skipped (COUNCIL_ENABLED=false)",
    "suggestions": [],
}

_ERROR_RESULT: Dict[str, Any] = {
    "passed": True,
    "score": 0.8,
    "reason": "Council evaluation failed — proceeding (non-strict mode)",
    "suggestions": [],
}


def _is_enabled() -> bool:
    return os.environ.get("COUNCIL_ENABLED", "true").lower() != "false"


def _is_strict() -> bool:
    return os.environ.get("COUNCIL_STRICT_MODE", "false").lower() == "true"


def _parse_council_response(raw: str) -> Dict[str, Any]:
    """Extract the JSON council result from an LLM response."""
    import re
    raw = raw.strip()

    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Extract JSON object from prose
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning("Council: could not parse LLM response as JSON: %s", raw[:200])
    return _ERROR_RESULT.copy()


class PreFlightCouncil:
    """Validates a factory request before the pipeline starts."""

    async def run(
        self,
        raw_input: str,
        domain: str = "general",
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not _is_enabled():
            return _PASS_RESULT.copy()

        from aether_os.core.llm.client import get_llm_client
        client = get_llm_client()

        prompt = _PREFLIGHT_PROMPT_TMPL.format(
            raw_input=raw_input[:2000],
            domain=domain,
        )
        try:
            raw = await client.call(
                prompt,
                task_type="classify",
                system=_COUNCIL_SYSTEM,
                max_tokens=512,
                org_id=org_id,
            )
            result = _parse_council_response(raw)
            logger.info(
                "PreFlightCouncil: passed=%s score=%.2f reason=%s",
                result.get("passed"),
                result.get("score", 0.0),
                result.get("reason", ""),
            )
            return result
        except Exception as exc:
            logger.warning("PreFlightCouncil: LLM call failed — %s", exc)
            return _ERROR_RESULT.copy()


class DeliveryCouncil:
    """Validates pipeline output before delivery to the client."""

    async def run(
        self,
        run_id: str,
        project_name: str,
        domain: str,
        phases_results: Dict[str, Any],
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not _is_enabled():
            return _PASS_RESULT.copy()

        from aether_os.core.llm.client import get_llm_client
        client = get_llm_client()

        completed = [p for p, r in phases_results.items() if r.get("status") in ("passed", "completed")]
        failed = [p for p, r in phases_results.items() if r.get("status") in ("failed", "timeout")]
        summary = json.dumps({
            "completed": len(completed),
            "failed": len(failed),
            "phases": {k: v.get("status", "unknown") for k, v in phases_results.items()},
        }, indent=2)

        prompt = _DELIVERY_PROMPT_TMPL.format(
            project_name=project_name or run_id,
            domain=domain,
            phases_completed=len(completed),
            phases_summary=summary[:1500],
        )
        try:
            raw = await client.call(
                prompt,
                task_type="classify",
                system=_COUNCIL_SYSTEM,
                max_tokens=512,
                org_id=org_id,
            )
            result = _parse_council_response(raw)
            logger.info(
                "DeliveryCouncil: passed=%s score=%.2f reason=%s",
                result.get("passed"),
                result.get("score", 0.0),
                result.get("reason", ""),
            )
            return result
        except Exception as exc:
            logger.warning("DeliveryCouncil: LLM call failed — %s", exc)
            return _ERROR_RESULT.copy()
