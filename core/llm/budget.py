"""
AetherOS — Token Budget Manager (PostgreSQL-backed)

Tracks per-org token spend and enforces plan limits.
Uses the shared token_budget_records table in PostgreSQL so all workers
see consistent usage — no per-process SQLite files.

Plan token budgets (per month):
  trial:      500K tokens  (~5 runs/month at average cost)
  starter:    5M tokens    (~50 runs/month)
  growth:     25M tokens   (~250 runs/month)
  enterprise: unlimited
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Monthly token budgets per plan
_PLAN_BUDGETS: Dict[str, int] = {
    "trial":      500_000,
    "starter":    5_000_000,
    "growth":    25_000_000,
    "enterprise": 999_999_999,  # effectively unlimited
}

_DOWNGRADE_THRESHOLD = 0.85   # switch to Haiku when >85% of budget used
_BLOCK_THRESHOLD     = 1.00   # block when 100% used (trial only)

# Input/output cost per token (USD).
# Anthropic claude-sonnet-4-6: $3/M input, $15/M output
# Separate dicts so record_usage() can apply correct per-direction rates.
_COST_PER_INPUT_TOKEN: Dict[str, float] = {
    "claude-sonnet-4-6":         3.00  / 1_000_000,
    "claude-haiku-4-5-20251001": 0.25  / 1_000_000,
    "gemini-2.5-flash":          0.15  / 1_000_000,
    "gemini-2.5-pro":            1.25  / 1_000_000,
    "default":                   3.00  / 1_000_000,
}
_COST_PER_OUTPUT_TOKEN: Dict[str, float] = {
    "claude-sonnet-4-6":         15.00 / 1_000_000,
    "claude-haiku-4-5-20251001":  1.25 / 1_000_000,
    "gemini-2.5-flash":           0.60 / 1_000_000,
    "gemini-2.5-pro":             5.00 / 1_000_000,
    "default":                   15.00 / 1_000_000,
}
# Legacy alias used by older callers
_COST_PER_TOKEN: Dict[str, float] = _COST_PER_INPUT_TOKEN


async def _get_or_create_record(session, org_id: str, month: str):
    """Return the TokenBudgetRecord for this org+month, creating it if missing."""
    from aether_os.core.models import TokenBudgetRecord
    from sqlalchemy import select
    row = (await session.execute(
        select(TokenBudgetRecord)
        .where(TokenBudgetRecord.org_id == org_id, TokenBudgetRecord.month == month)
    )).scalar_one_or_none()
    if row is None:
        row = TokenBudgetRecord(org_id=org_id, month=month)
        session.add(row)
        await session.flush()
    return row


class TokenBudgetManager:
    """Check and record token usage per org against monthly plan budgets."""

    async def get_usage(self, org_id: str, month: Optional[str] = None) -> dict:
        m = month or time.strftime("%Y-%m")
        try:
            from aether_os.core.db import get_session_factory
            sf = get_session_factory()
            async with sf() as session:
                row = await _get_or_create_record(session, org_id, m)
                await session.commit()
                return {
                    "input_tokens":       row.input_tokens,
                    "output_tokens":      row.output_tokens,
                    "cache_hits":         row.cache_hits,
                    "cache_misses":       row.cache_misses,
                    "runs":               row.runs,
                    "estimated_cost_usd": row.estimated_cost_usd,
                    "total_tokens":       row.input_tokens + row.output_tokens,
                }
        except Exception as exc:
            logger.debug("Budget get_usage failed: %s", exc)
        return {"input_tokens": 0, "output_tokens": 0, "cache_hits": 0,
                "cache_misses": 0, "runs": 0, "estimated_cost_usd": 0.0, "total_tokens": 0}

    async def check_budget(self, org_id: str, plan: str) -> Tuple[bool, str, str]:
        if plan == "enterprise":
            return True, "ok", "sonnet"
        month = time.strftime("%Y-%m")
        usage = await self.get_usage(org_id, month)
        budget = _PLAN_BUDGETS.get(plan, _PLAN_BUDGETS["trial"])
        fraction = usage["total_tokens"] / max(budget, 1)
        if plan == "trial" and fraction >= _BLOCK_THRESHOLD:
            return False, f"Monthly budget exhausted ({usage['total_tokens']:,}/{budget:,} tokens)", "none"
        if fraction >= _DOWNGRADE_THRESHOLD:
            return True, f"Budget {fraction:.0%} used — downgrading to Haiku", "haiku"
        return True, "ok", "sonnet"

    async def record_usage(
        self,
        org_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str = "claude-sonnet-4-6",
        cache_hit: bool = False,
    ) -> None:
        month = time.strftime("%Y-%m")
        # Apply separate input and output rates (Anthropic: $3/$15 per million tokens)
        cost = (
            input_tokens  * _COST_PER_INPUT_TOKEN.get(model, _COST_PER_INPUT_TOKEN["default"]) +
            output_tokens * _COST_PER_OUTPUT_TOKEN.get(model, _COST_PER_OUTPUT_TOKEN["default"])
        )
        try:
            from aether_os.core.db import get_session_factory
            sf = get_session_factory()
            async with sf() as session:
                row = await _get_or_create_record(session, org_id, month)
                row.input_tokens       += input_tokens
                row.output_tokens      += output_tokens
                row.cache_hits         += 1 if cache_hit else 0
                row.cache_misses       += 0 if cache_hit else 1
                row.runs               += 1
                row.estimated_cost_usd += cost
                row.updated_at          = time.time()
                await session.commit()
        except Exception as exc:
            logger.debug("Budget record_usage failed: %s", exc)

    async def get_cost_report(self, org_id: str, months: int = 3) -> list:
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import TokenBudgetRecord
            from sqlalchemy import select
            sf = get_session_factory()
            async with sf() as session:
                rows = (await session.execute(
                    select(TokenBudgetRecord)
                    .where(TokenBudgetRecord.org_id == org_id)
                    .order_by(TokenBudgetRecord.month.desc())
                    .limit(months)
                )).scalars().all()
            return [
                {
                    "month":              r.month,
                    "input_tokens":       r.input_tokens,
                    "output_tokens":      r.output_tokens,
                    "cache_hits":         r.cache_hits,
                    "cache_misses":       r.cache_misses,
                    "runs":               r.runs,
                    "estimated_cost_usd": round(r.estimated_cost_usd, 4),
                    "cost_per_run":       round(r.estimated_cost_usd / max(r.runs, 1), 4),
                    "cache_hit_rate":     round(r.cache_hits / max(r.cache_hits + r.cache_misses, 1), 3),
                }
                for r in rows
            ]
        except Exception as exc:
            logger.debug("Budget cost_report failed: %s", exc)
            return []


# ── Singleton ─────────────────────────────────────────────────────────────────

_budget_manager: Optional[TokenBudgetManager] = None


def get_budget_manager() -> TokenBudgetManager:
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = TokenBudgetManager()
    return _budget_manager
