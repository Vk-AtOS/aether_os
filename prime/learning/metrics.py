"""Prime learning (KAN-229): is the learning helping? Per ISO week (Monday, UTC), for one organisation:

    help rate per kind       settled uses that helped / settled uses
    build first-pass rate    runs whose first frontend build was green in round 1 / runs built
    correction rate          corrections stored / approval requests decided

Rows are read for the window only and counted here, so the same code runs on PostgreSQL and SQLite.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.prime.learning.loop import KINDS
from aether_os.prime.learning.models import LearningBuildOutcome, LearningUse

MAX_WEEKS = 26


def week_of(dt: datetime) -> str:
    d: date = dt.date()
    return (d - timedelta(days=d.weekday())).isoformat()


def _rate(num: int, den: int) -> Optional[float]:
    return round(num / den, 3) if den else None


async def weekly(org_id: str, weeks: int = 12, now: Optional[datetime] = None) -> Dict[str, Any]:
    from aether_os.prime.models import PrimeCorrection, PrimeRequest
    weeks = max(1, min(weeks, MAX_WEEKS))
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    first = datetime.fromisoformat(week_of(now)) - timedelta(weeks=weeks - 1)
    keys = [(first + timedelta(weeks=i)).date().isoformat() for i in range(weeks)]
    rows: Dict[str, Dict[str, Any]] = {k: {"week": k, "kinds": {kind: {"settled": 0, "helped": 0} for kind in KINDS},
                                           "builds": 0, "first_pass": 0, "corrections": 0, "decided": 0}
                                       for k in keys}
    async with get_session_factory()() as s:
        uses = (await s.execute(select(LearningUse.kind, LearningUse.helped, LearningUse.settled_at).where(
            LearningUse.org_id == org_id, LearningUse.settled_at >= first))).all()
        builds = (await s.execute(select(LearningBuildOutcome.first_pass, LearningBuildOutcome.created_at).where(
            LearningBuildOutcome.org_id == org_id, LearningBuildOutcome.created_at >= first))).all()
        made = (await s.execute(select(PrimeCorrection.created_at).where(
            PrimeCorrection.org_id == org_id, PrimeCorrection.created_at >= first))).scalars().all()
        decided = (await s.execute(select(PrimeRequest.decided_at).where(
            PrimeRequest.org_id == org_id, PrimeRequest.decided_at >= first))).scalars().all()
    for kind, helped, at in uses:
        row = rows.get(week_of(at))
        if row and kind in row["kinds"]:
            row["kinds"][kind]["settled"] += 1
            row["kinds"][kind]["helped"] += 1 if helped else 0
    for first_pass, at in builds:
        if (row := rows.get(week_of(at))) is not None:
            row["builds"] += 1
            row["first_pass"] += 1 if first_pass else 0
    for at in made:
        if (row := rows.get(week_of(at))) is not None:
            row["corrections"] += 1
    for at in decided:
        if (row := rows.get(week_of(at))) is not None:
            row["decided"] += 1
    out: List[Dict[str, Any]] = []
    for k in keys:
        row = rows[k]
        for v in row["kinds"].values():
            v["help_rate"] = _rate(v["helped"], v["settled"])
        row["first_pass_rate"] = _rate(row["first_pass"], row["builds"])
        row["correction_rate"] = _rate(row["corrections"], row["decided"])
        out.append(row)
    totals = {kind: {"settled": sum(r["kinds"][kind]["settled"] for r in out),
                     "helped": sum(r["kinds"][kind]["helped"] for r in out)} for kind in KINDS}
    for v in totals.values():
        v["help_rate"] = _rate(v["helped"], v["settled"])
    return {"weeks": out, "totals": totals}
