"""Improvement Loop — continuous feedback-driven quality improvement."""
from __future__ import annotations
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_instance: Optional["ImprovementLoop"] = None


class ImprovementLoop:
    """Aggregates feedback from pipeline runs and drives iterative improvements.

    Sources of feedback:
    - Test failures and coverage metrics
    - Security findings
    - Client approval/rejection decisions
    - Performance benchmarks
    - Human operator corrections
    """

    async def collect_feedback(self, run_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
        """Collect all feedback signals for a completed run."""
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Run, Decision
            from sqlalchemy import select
            async with get_session_factory()() as sess:
                run = await sess.get(Run, run_id)
                if not run:
                    return {"error": "Run not found"}
                phases = run.phases or {}
                decisions = (await sess.execute(
                    select(Decision).where(Decision.run_id == run_id)
                )).scalars().all()

            signals = {
                "run_id": run_id,
                "status": run.status,
                "phase_pass_rate": sum(
                    1 for p in phases.values()
                    if p.get("status") in ("passed", "completed")
                ) / max(len(phases), 1),
                "cost": run.cost,
                "human_decisions": [{"id": d.id, "status": d.status} for d in decisions],
                "collected_at": time.time(),
            }
            return signals
        except Exception as exc:
            logger.warning("ImprovementLoop collect_feedback failed: %s", exc)
            return {"error": str(exc)}

    async def generate_improvements(self, feedback: Dict[str, Any]) -> Dict[str, Any]:
        """Use LLM to generate improvement recommendations from feedback signals."""
        try:
            from aether_os.core.llm.client import get_llm_client
            llm = get_llm_client()
            prompt = (
                f"You are a software quality improvement advisor.\n\n"
                f"Run feedback:\n{str(feedback)[:2000]}\n\n"
                f"Suggest concrete improvements. Return JSON:\n"
                f"{{'improvements': [{{'area': str, 'suggestion': str, 'priority': 'high'|'medium'|'low'}}], "
                f"'estimated_quality_gain': '0-100%'}}"
            )
            result = await llm.call_json(prompt, task_type="documentation")
            return {**result, "engine": "improvement_loop"}
        except Exception as exc:
            logger.warning("improvement_loop.generate_improvements failed: %s", exc)
            return {"improvements": [], "estimated_quality_gain": "unknown", "engine": "improvement_loop", "error": str(exc)}

    async def run_cycle(self, run_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
        """Full improvement cycle: collect → analyze → recommend."""
        feedback = await self.collect_feedback(run_id, org_id)
        if "error" in feedback:
            return feedback
        improvements = await self.generate_improvements(feedback)
        return {"feedback": feedback, **improvements}


def get_improvement_loop() -> ImprovementLoop:
    global _instance
    if _instance is None:
        _instance = ImprovementLoop()
    return _instance
