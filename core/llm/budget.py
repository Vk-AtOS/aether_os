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

import json
import logging
import os
import time
import uuid
from typing import Dict, Optional, Tuple

from aether_os.core.llm.plans import PLAN_LIMITS, token_cap_for
from aether_os.core.telemetry.metrics import BUDGET_ALERTS, observe_cost

logger = logging.getLogger(__name__)

# Monthly token budgets per plan (derived from core.llm.plans, the one table of plan limits).
_PLAN_BUDGETS: Dict[str, int] = {name: lim.tokens for name, lim in PLAN_LIMITS.items()}

_DOWNGRADE_THRESHOLD = 0.85   # switch to Haiku when >85% of budget used
_ALERT_THRESHOLD     = 0.80   # alert once per org/month at 80%
_BLOCK_THRESHOLD     = 1.00   # hard stop at 100% for every plan (D6)
_alerted: set = set()


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def daily_cap_usd(monthly_cap: float) -> float:
    """One organisation may spend at most LLM_DAILY_SHARE (default 0.25) of its monthly USD cap in one UTC day, but never
    less than min(cap, $2): a looping agent cannot burn the month in a day, a normal first run is not blocked.
    LLM_DAILY_SHARE=1 switches the daily limit off. The share is a default for the owner to review."""
    share = max(0.0, min(1.0, float(os.environ.get("LLM_DAILY_SHARE", "0.25"))))
    return max(monthly_cap * share, min(monthly_cap, 2.0))


async def _daily_spent(session, org_id: str, day: str) -> float:
    from aether_os.core.models_ops import LlmDailyUsage
    from sqlalchemy import select
    return (await session.execute(select(LlmDailyUsage.cost_usd).where(
        LlmDailyUsage.org_id == org_id, LlmDailyUsage.day == day))).scalar() or 0.0


async def _add_daily(session, org_id: str, day: str, cost: float) -> None:
    from aether_os.core.models_ops import LlmDailyUsage as D
    from sqlalchemy import update
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    await session.execute(insert(D).values(id=str(uuid.uuid4()), org_id=org_id, day=day, cost_usd=0.0)
                          .on_conflict_do_nothing(index_elements=["org_id", "day"]))
    await session.execute(update(D).where(D.org_id == org_id, D.day == day).values(cost_usd=D.cost_usd + cost))


async def _alert_80(org_id: str, month: str, pct: float, plan: str) -> None:
    """Tell the org (an org-wide in-app notification, once per month) that it is near its cap."""
    if (org_id, month) in _alerted:
        return
    _alerted.add((org_id, month))
    BUDGET_ALERTS.inc()
    logger.warning("LLM budget ALERT: org %s used %.0f%% of its %s monthly allowance", org_id, pct * 100, plan)
    try:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import Notification
        from sqlalchemy import select
        kind = f"llm_budget_80:{month}"
        async with get_session_factory()() as session:
            seen = (await session.execute(
                select(Notification.id).where(Notification.org_id == org_id, Notification.type == kind).limit(1)
            )).first()
            if not seen:
                session.add(Notification(
                    org_id=org_id, user_id=None, type=kind, title="AI usage at 80% of this month's limit",
                    message=f"Your organisation has used {pct:.0%} of its monthly AI allowance ({plan} plan). "
                            "Calls stop at 100% until next month or until the limit is raised.",
                ))
                await session.commit()
    except Exception as exc:
        logger.warning("Could not store the 80%% budget notification for %s: %s", org_id, exc)

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

def _price_overrides() -> Dict[str, Tuple[float, float]]:
    """Operator-set prices in USD per 1K tokens: env LLM_PRICES_PER_1K='{"model": [in, out]}'.
    Needed because OpenRouter/NVIDIA report no price: without it a paid model on those providers would count as
    free (or as Sonnet) and the spend cap would be wrong."""
    raw = os.environ.get("LLM_PRICES_PER_1K", "").strip()
    if not raw:
        return {}
    try:
        return {m: (float(v[0]), float(v[1])) for m, v in json.loads(raw).items()}
    except Exception as exc:
        logger.warning("LLM_PRICES_PER_1K ignored, not valid JSON of model -> [in, out]: %s", exc)
        return {}


def _is_free_model(model: str) -> bool:
    return model.endswith(":free") or model.startswith(("nvidia/", "nvidia_nim/")) or model in ("cache", "local")


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Cost of one call. Order: operator price per 1K, known price table, free models cost 0, anything else is
    priced at the conservative default so an unknown paid model can never slip under the cap."""
    override = _price_overrides().get(model)
    if override:
        return (input_tokens * override[0] + output_tokens * override[1]) / 1000
    if model not in _COST_PER_INPUT_TOKEN and _is_free_model(model):
        return 0.0
    return (input_tokens * _COST_PER_INPUT_TOKEN.get(model, _COST_PER_INPUT_TOKEN["default"])
            + output_tokens * _COST_PER_OUTPUT_TOKEN.get(model, _COST_PER_OUTPUT_TOKEN["default"]))


# Legacy alias used by older callers
_COST_PER_TOKEN: Dict[str, float] = _COST_PER_INPUT_TOKEN


async def _get_or_create_record(session, org_id: str, month: str):
    """Return the TokenBudgetRecord for this org+month, creating it if missing.

    INSERT .. ON CONFLICT DO NOTHING against the unique (org_id, month): concurrent
    first calls of a month converge on one row instead of inserting two.
    """
    from aether_os.core.models import TokenBudgetRecord
    from sqlalchemy import select
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    await session.execute(
        insert(TokenBudgetRecord)
        .values(id=str(uuid.uuid4()), org_id=org_id, month=month, input_tokens=0, output_tokens=0,
                runs=0, cache_hits=0, cache_misses=0, estimated_cost_usd=0.0, updated_at=time.time())
        .on_conflict_do_nothing(index_elements=["org_id", "month"])
    )
    return (await session.execute(
        select(TokenBudgetRecord)
        .where(TokenBudgetRecord.org_id == org_id, TokenBudgetRecord.month == month)
    )).scalar_one()


class TokenBudgetManager:
    """Check and record token usage per org against monthly plan budgets."""

    async def get_usage(self, org_id: str, month: Optional[str] = None, strict: bool = False) -> dict:
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
            if strict:
                raise  # the spend cap must fail closed: unknown usage is not zero usage
            logger.debug("Budget get_usage failed: %s", exc)
        return {"input_tokens": 0, "output_tokens": 0, "cache_hits": 0,
                "cache_misses": 0, "runs": 0, "estimated_cost_usd": 0.0, "total_tokens": 0}

    async def check_budget(self, org_id: str, plan: str, projected_cost_usd: float = 0.0,
                           cap_usd: Optional[float] = None, token_cap: Optional[int] = None) -> Tuple[bool, str, str]:
        """(allowed, reason, model hint). Both the token and the USD allowance are hard stops; the
        USD side counts this call's worst case (`projected_cost_usd`) so the cap is not overshot
        by a large request. An unknown plan is refused, not given the trial allowance."""
        limit = PLAN_LIMITS.get(plan)
        if limit is None:
            return False, f"Unknown plan {plan!r}: no AI allowance defined", "none"
        month = time.strftime("%Y-%m")
        usage = await self.get_usage(org_id, month, strict=True)
        cap = limit.usd if cap_usd is None else cap_usd
        spent = usage["estimated_cost_usd"] or 0.0
        usd_fraction = (spent + projected_cost_usd) / cap if cap > 0 else 1.0
        tokens_cap = token_cap_for(plan, token_cap)
        token_fraction = usage["total_tokens"] / max(tokens_cap, 1)
        fraction = max(token_fraction, usd_fraction)
        # Say WHICH limit stopped the call: "$0.00 of $200.00" next to a token count read as a money problem (KAN-261).
        if token_fraction >= _BLOCK_THRESHOLD:
            return False, (f"Monthly AI TOKEN limit exhausted ({usage['total_tokens']:,} of {tokens_cap:,} tokens used; "
                           f"cost so far ${spent:,.2f} of the ${cap:,.2f} spend cap, which is not the limit that was hit). "
                           "Ask an admin to raise the organisation's token limit."), "none"
        if usd_fraction >= _BLOCK_THRESHOLD:
            return False, (f"Monthly AI SPEND limit exhausted (${spent:,.2f} of ${cap:,.2f}; "
                           f"{usage['total_tokens']:,} of {tokens_cap:,} tokens used)"), "none"
        daily_cap = daily_cap_usd(cap)
        from aether_os.core.db import get_session_factory
        async with get_session_factory()() as session:      # unreadable usage raises: the cap fails closed
            today = await _daily_spent(session, org_id, _today())
        if daily_cap > 0 and today + projected_cost_usd >= daily_cap and daily_cap < cap:
            return False, (f"Daily AI allowance reached (${today:,.2f} of ${daily_cap:,.2f} today). "
                           "It resets at 00:00 UTC, or ask an admin to raise the plan limit."), "none"
        if fraction >= _ALERT_THRESHOLD:
            await _alert_80(org_id, month, fraction, plan)
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
        cost = cost_usd(model, input_tokens, output_tokens)
        observe_cost(model, input_tokens, output_tokens, cost)
        try:
            from aether_os.core.db import get_session_factory
            sf = get_session_factory()
            async with sf() as session:
                from aether_os.core.models import TokenBudgetRecord as T
                from sqlalchemy import update
                await _get_or_create_record(session, org_id, month)
                # Atomic increments: a read-modify-write here loses concurrent updates
                # and under-counts the spend the cap is enforced against.
                await session.execute(
                    update(T).where(T.org_id == org_id, T.month == month).values(
                        input_tokens=T.input_tokens + input_tokens,
                        output_tokens=T.output_tokens + output_tokens,
                        cache_hits=T.cache_hits + (1 if cache_hit else 0),
                        cache_misses=T.cache_misses + (0 if cache_hit else 1),
                        runs=T.runs + 1,
                        estimated_cost_usd=T.estimated_cost_usd + cost,
                        updated_at=time.time(),
                    )
                )
                await _add_daily(session, org_id, _today(), cost)
                await session.commit()
        except Exception as exc:
            logger.warning("Budget record_usage failed (spend not recorded): %s", exc)

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
