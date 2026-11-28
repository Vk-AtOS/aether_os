"""Billing-ledger bookkeeping for a served model call, split out of model_router.py (600-line limit).

Everything here is best-effort: a failed ledger write must never fail a call that already has its answer.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Set

from aether_os.core.run_context import ACTIVE_ORG_ID, ACTIVE_PHASE, ACTIVE_RUN_ID

logger = logging.getLogger(__name__)


async def record_billing(spec, org_id, _est_input: int, _est_output: int, tasks: Set[asyncio.Task]) -> None:
    """Book the call to the billing ledger and the org token budget (background tasks, kept in `tasks`)."""
    # Record cost to billing ledger using active run context vars
    try:
        _run_id = ACTIVE_RUN_ID.get(None)
        _phase = ACTIVE_PHASE.get("unknown")
        if _run_id:
            _COST_PER_1M = {
                "anthropic":  (3.0, 15.0),
                "gemini":     (0.35, 1.05),
                "ollama":     (0.0, 0.0),
                "openrouter": (0.5, 1.5),
            }
            _in_rate, _out_rate = _COST_PER_1M.get(spec.provider, (0.5, 1.5))
            _cost_usd = (_est_input * _in_rate + _est_output * _out_rate) / 1_000_000
            from aether_os.core.billing import get_billing_tracker
            _org_id = ACTIVE_ORG_ID.get("") or os.environ.get("ACTIVE_ORG_ID", "-")
            _ct3 = asyncio.create_task(
                get_billing_tracker()._async_record_llm_call(
                    org_id=_org_id,
                    project_id=_run_id,
                    phase=_phase,
                    model=f"{spec.provider}/{spec.model}",
                    input_tokens=_est_input,
                    output_tokens=_est_output,
                    cost_usd=_cost_usd,
                )
            )
            tasks.add(_ct3)
            _ct3.add_done_callback(tasks.discard)
            # Also write to TokenBudgetRecord (org-level dashboard stats)
            if not org_id:
                try:
                    from aether_os.core.db import get_session_factory as _gsf_mr
                    from aether_os.core.models import Run as _Run_mr
                    from sqlalchemy import select as _sel_mr

                    async def _get_org():
                        async with _gsf_mr()() as _s:
                            r = await _s.execute(_sel_mr(_Run_mr.org_id).where(_Run_mr.id == _run_id))
                            return r.scalar_one_or_none()

                    _resolved_org = await _get_org()
                except Exception as exc:
                    logger.debug("Org ID resolve from run failed: %s", exc)
                    _resolved_org = None
            else:
                # The router already booked this call to org_id's budget; a second booking doubled every explicit-org call.
                _resolved_org = None
            if _resolved_org:
                from aether_os.core.llm.budget import get_budget_manager
                _ct4 = asyncio.create_task(
                    get_budget_manager().record_usage(
                        org_id=_resolved_org,
                        input_tokens=_est_input,
                        output_tokens=_est_output,
                        model=spec.model,
                        cache_hit=False,
                    )
                )
                tasks.add(_ct4)
                _ct4.add_done_callback(tasks.discard)
    except Exception as exc:
        logger.debug("Billing ledger record failed (non-fatal): %s", exc)
