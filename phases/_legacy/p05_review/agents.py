"""
AetherOS — Phase 05 Review Agents
Adapted from aether2 ReviewAgent and Aether-one code_review_agent.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List

from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


class ReviewAgent:
    name = "review_agent"

    async def run(self, code: str, context: Dict[str, Any]) -> Dict[str, Any]:
        llm = get_llm_client()
        language = context.get("language", "python")
        prompt = (
            f"Review this {language} code for bugs, style issues, correctness, and maintainability.\n\n"
            f"Return JSON: {{\"findings\": [\"...\"], \"overall_quality\": 0-10, \"critical_issues\": [\"...\"]}}\n\n"
            f"Code:\n{code[:8000]}"
        )
        result = await llm.call_json(prompt, task_type="code_generation")
        findings: List[str] = result.get("findings", [])
        logger.info("ReviewAgent found %d issues, quality=%s", len(findings), result.get("overall_quality"))
        return {"review_findings": findings, "review_details": result}
