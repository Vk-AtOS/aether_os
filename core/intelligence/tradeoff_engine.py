"""Tradeoff Engine — analyzes architectural and design tradeoffs."""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_instance: Optional["TradeoffEngine"] = None

TRADEOFF_DIMENSIONS = [
    "performance", "cost", "reliability", "security",
    "scalability", "maintainability", "time_to_market", "complexity",
]


class TradeoffEngine:
    """Analyzes tradeoffs between design options and recommends the best fit
    given the project's constraints and priorities.

    Examples:
    - Microservices vs. monolith given team size and scale
    - SQL vs. NoSQL given query patterns
    - Sync vs. async given throughput requirements
    """

    async def analyze(
        self,
        option_a: str,
        option_b: str,
        requirements: str = "",
        domain: str = "general",
    ) -> Dict[str, Any]:
        """Compare two architectural options across standard dimensions."""
        try:
            from aether_os.core.llm.client import get_llm_client
            llm = get_llm_client()
            dims = ", ".join(TRADEOFF_DIMENSIONS)
            prompt = (
                f"You are an architectural tradeoff advisor.\n\n"
                f"Option A: {option_a}\nOption B: {option_b}\n"
                f"Domain: {domain}\n"
                + (f"Requirements: {requirements[:1000]}\n" if requirements else "")
                + f"\nScore each option across: {dims} (0-10 scale).\n"
                f"Return JSON: {{'option_a': {{'name': str, 'scores': dict, 'pros': [str], 'cons': [str]}}, "
                f"'option_b': {{'name': str, 'scores': dict, 'pros': [str], 'cons': [str]}}, "
                f"'recommendation': 'A'|'B'|'neither', 'rationale': str}}"
            )
            result = await llm.call_json(prompt, task_type="code_generation")
            return {**result, "engine": "tradeoff_engine"}
        except Exception as e:
            logger.warning("tradeoff_engine LLM unavailable, using static fallback: %s", e)
            return {
                "option_a": {"name": option_a, "scores": {}, "pros": [], "cons": []},
                "option_b": {"name": option_b, "scores": {}, "pros": [], "cons": []},
                "recommendation": "neither",
                "rationale": "LLM unavailable — static fallback cannot evaluate tradeoffs",
                "engine": "static_fallback",
                "note": "LLM unavailable — run manual tradeoff analysis",
            }

    async def evaluate_run_choices(self, run_id: str) -> Dict[str, Any]:
        """Evaluate key architectural choices made during a run."""
        return {"run_id": run_id, "choices_evaluated": 0, "engine": "tradeoff_engine"}


def get_tradeoff_engine() -> TradeoffEngine:
    global _instance
    if _instance is None:
        _instance = TradeoffEngine()
    return _instance
