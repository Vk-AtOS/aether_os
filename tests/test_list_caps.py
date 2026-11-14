"""Child lists have a hard maximum page size (KAN-136)."""
import asyncio

from sqlalchemy import select
from sqlalchemy.dialects import sqlite

import aether_os.core.services.run_service as rs


def test_clamp_limit_bounds():
    assert rs.clamp_limit(10**9) == rs.MAX_PAGE
    assert rs.clamp_limit(0) == 1
    assert rs.clamp_limit(-5) == 1
    assert rs.clamp_limit("abc") == 100


def test_unbounded_run_child_queries_carry_a_limit():
    captured = []

    class Sess:
        async def execute(self, stmt):
            captured.append(str(stmt.compile(dialect=sqlite.dialect())))

            class R:
                def all(self):
                    return []

                def scalars(self):
                    return self

                def scalar_one_or_none(self):
                    return None
            return R()

        async def get(self, model, pk):
            class Run:
                org_id = "o"
            return Run()

    async def go():
        await rs.get_phase_completions(Sess(), "r")
        await rs.get_explicit_events(Sess(), "r")
        await rs.get_run_snapshots(Sess(), "r", "o", limit=10**9)

    asyncio.run(go())
    assert len(captured) == 3 and all("LIMIT" in q for q in captured)
