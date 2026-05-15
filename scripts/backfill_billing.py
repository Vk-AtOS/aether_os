"""
Backfill LLMCallRecord rows for completed runs that have no billing data.

Run once:  python3 scripts/backfill_billing.py

Strategy: for each completed run with zero LLMCallRecord rows, synthesise
approximate records from PhaseCompletion rows using median token estimates
per phase type.  These are estimates only — real usage tracking begins
from the point the pipeline records calls at runtime.
"""
from __future__ import annotations
import asyncio
import time
import uuid
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Per-phase median token estimates (input, output) based on typical LLM usage
_PHASE_TOKENS: dict[str, tuple[int, int]] = {
    "p01": (1_200, 800),
    "p02": (2_500, 2_000),
    "p03": (1_800, 3_500),
    "p04": (3_000, 6_000),
    "p05": (2_000, 4_000),
    "p06": (2_200, 1_500),
    "p07": (1_500, 1_200),
    "p08": (1_200, 1_800),
    "p09": (1_000, 1_400),
    "p10": (1_500, 2_500),
    "p11": (800,  1_200),
    "p12": (700,  1_000),
    "p13": (600,   900),
    "p14": (500,   800),
}

# Cost per 1M tokens (input / output) — Claude Sonnet 4 pricing
_COST_PER_1M = {"input": 3.0, "output": 15.0}


def _estimate_cost(input_tok: int, output_tok: int) -> float:
    return (input_tok / 1_000_000 * _COST_PER_1M["input"] +
            output_tok / 1_000_000 * _COST_PER_1M["output"])


def _phase_key(phase_name: str) -> str:
    """Extract p01..p14 prefix from phase name like 'p04_backend'."""
    import re
    m = re.match(r"(p\d{2})", phase_name.lower())
    return m.group(1) if m else "p01"


async def main() -> None:
    from core.db import get_session_factory
    from core.models import Run, PhaseCompletion, LLMCallRecord
    from sqlalchemy import select, func

    sf = get_session_factory()
    async with sf() as session:
        # Find all runs that have at least one phase completion
        from sqlalchemy import text as _text
        run_ids_with_phases = (
            select(PhaseCompletion.run_id).distinct()
        )
        runs_result = await session.execute(
            select(Run).where(Run.id.in_(run_ids_with_phases))
        )
        runs = runs_result.scalars().all()
        print(f"Found {len(runs)} completed runs")

        backfilled = 0
        for run in runs:
            # Check if run already has billing records
            count_result = await session.execute(
                select(func.count(LLMCallRecord.id)).where(
                    LLMCallRecord.project_id == run.id
                )
            )
            existing = count_result.scalar_one()
            if existing > 0:
                continue  # already has data

            # Get phases for this run
            phases_result = await session.execute(
                select(PhaseCompletion).where(
                    PhaseCompletion.run_id == run.id
                )
            )
            phases = phases_result.scalars().all()
            if not phases:
                continue

            model = "claude-sonnet-4-6"  # best guess for historical runs

            for phase in phases:
                pk = _phase_key(phase.phase_name)
                in_tok, out_tok = _PHASE_TOKENS.get(pk, (1_000, 1_000))
                cost = _estimate_cost(in_tok, out_tok)
                record = LLMCallRecord(
                    id=str(uuid.uuid4()),
                    org_id=run.org_id,
                    project_id=run.id,
                    phase=phase.phase_name,
                    model=model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cost_usd=cost,
                    created_at=getattr(phase, 'completed_at', None) or getattr(phase, 'updated_at', None) or time.time(),
                )
                session.add(record)
                backfilled += 1

        await session.commit()
        print(f"Backfilled {backfilled} LLMCallRecord rows across {len(runs)} runs")


if __name__ == "__main__":
    asyncio.run(main())
