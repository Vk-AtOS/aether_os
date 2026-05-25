"""AetherOS — Per-project usage and billing tracker — ORM edition (C1).

Migrated from billing.db (sqlite3) to the shared PostgreSQL ORM.
External API (`record_llm_call`, `record_phase_completion`, `get_project_cost`) unchanged.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Anthropic pricing (USD per 1M tokens, as of 2025)
_TOKEN_PRICES: Dict[str, Dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5":  {"input": 0.25,  "output": 1.25},
    "claude-opus-4-6":   {"input": 15.00, "output": 75.00},
    "default":           {"input": 3.00,  "output": 15.00},
}


@dataclass
class CostSummary:
    project_id: str
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    phase_breakdown: Dict[str, float]


class UsageTracker:
    @staticmethod
    def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        prices = _TOKEN_PRICES.get(model, _TOKEN_PRICES["default"])
        return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000

    def record_llm_call(self, project_id: str, phase: str, model: str,
                        input_tokens: int, output_tokens: int,
                        cost_usd: Optional[float] = None) -> None:
        if cost_usd is None:
            cost_usd = self._calc_cost(model, input_tokens, output_tokens)
        _run_async(self._async_record_llm_call(project_id, phase, model, input_tokens, output_tokens, cost_usd))

    def record_phase_completion(self, project_id: str, phase: str,
                                duration_s: float) -> None:
        _run_async(self._async_record_phase_completion(project_id, phase, duration_s))

    def get_project_cost(self, project_id: str) -> CostSummary:
        return _run_async(self._async_get_project_cost(project_id)) or CostSummary(
            project_id=project_id,
            total_input_tokens=0, total_output_tokens=0,
            total_cost_usd=0.0, phase_breakdown={},
        )

    def get_phase_cost(self, project_id: str, phase: str) -> float:
        return _run_async(self._async_get_phase_cost(project_id, phase)) or 0.0

    # ── Async implementations ─────────────────────────────────────────────────

    async def _async_record_llm_call(self, project_id: str, phase: str, model: str,
                                     input_tokens: int, output_tokens: int,
                                     cost_usd: float) -> None:
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import LLMCallRecord
            sf = get_session_factory()
            async with sf() as session:
                session.add(LLMCallRecord(
                    project_id=project_id, phase=phase, model=model,
                    input_tokens=input_tokens, output_tokens=output_tokens,
                    cost_usd=cost_usd, created_at=time.time(),
                ))
                await session.commit()
        except Exception as exc:
            logger.debug("record_llm_call failed: %s", exc)

    async def _async_record_phase_completion(self, project_id: str, phase: str,
                                             duration_s: float) -> None:
        try:
            from aether_os.core.db_utils import record_phase_completion
            await record_phase_completion(
                run_id=project_id, phase_name=phase,
                status="completed", duration_s=duration_s,
            )
        except Exception as exc:
            logger.debug("record_phase_completion failed: %s", exc)

    async def _async_get_project_cost(self, project_id: str) -> CostSummary:
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import LLMCallRecord
            from sqlalchemy import select, func

            sf = get_session_factory()
            async with sf() as session:
                row = (await session.execute(
                    select(
                        func.coalesce(func.sum(LLMCallRecord.input_tokens), 0),
                        func.coalesce(func.sum(LLMCallRecord.output_tokens), 0),
                        func.coalesce(func.sum(LLMCallRecord.cost_usd), 0.0),
                    ).where(LLMCallRecord.project_id == project_id)
                )).one()

                phase_rows = (await session.execute(
                    select(LLMCallRecord.phase, func.coalesce(func.sum(LLMCallRecord.cost_usd), 0.0))
                    .where(LLMCallRecord.project_id == project_id)
                    .group_by(LLMCallRecord.phase)
                )).all()

            return CostSummary(
                project_id=project_id,
                total_input_tokens=int(row[0]),
                total_output_tokens=int(row[1]),
                total_cost_usd=round(float(row[2]), 6),
                phase_breakdown={r[0]: round(float(r[1]), 6) for r in phase_rows},
            )
        except Exception as exc:
            logger.debug("get_project_cost failed: %s", exc)
            return CostSummary(
                project_id=project_id,
                total_input_tokens=0, total_output_tokens=0,
                total_cost_usd=0.0, phase_breakdown={},
            )

    async def _async_get_phase_cost(self, project_id: str, phase: str) -> float:
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import LLMCallRecord
            from sqlalchemy import select, func

            sf = get_session_factory()
            async with sf() as session:
                row = (await session.execute(
                    select(func.coalesce(func.sum(LLMCallRecord.cost_usd), 0.0))
                    .where(LLMCallRecord.project_id == project_id, LLMCallRecord.phase == phase)
                )).scalar_one()
            return round(float(row), 6)
        except Exception as exc:
            logger.debug("get_phase_cost failed: %s", exc)
            return 0.0


# ── Helper ────────────────────────────────────────────────────────────────────

# Strong references for background tasks (prevents GC from killing in-flight coroutines)
_background_tasks: set = set()


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
        # Inside an event loop — fire-and-forget with strong reference
        task = loop.create_task(coro)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return None
    except RuntimeError:
        # No running loop — use asyncio.run
        return asyncio.run(coro)


# ── Singleton ─────────────────────────────────────────────────────────────────

_tracker: Optional[UsageTracker] = None


def get_usage_tracker() -> UsageTracker:
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker


# Alias — used by model_router.py and llm/client.py
get_billing_tracker = get_usage_tracker
