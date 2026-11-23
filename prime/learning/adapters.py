"""Prime learning (KAN-229): the three learners behind one record shape, and the calls that put them into prompts.

    correction  prime_corrections (KAN-24)   approver edits / reasoned rejections, per agent and action type
    golden      golden_builds                highly rated builds, few-shot examples for p04a and p05
    fix         fix_memory (KAN-215)         build-error fixes replayed without a model call

Each keeps its own table; an item is addressed as (org_id, kind, item_id). Every read filters by org_id. Correction
text is pseudonymised with the pseudonymiser of prime/corrections.py before it reaches a prompt or the screen.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import case, func, select

from aether_os.core.db import get_session_factory
from aether_os.core.run_context import ACTIVE_RUN_ID
from aether_os.prime import corrections
from aether_os.prime.learning import loop
from aether_os.prime.learning.models import LearningItemState, LearningUse

logger = logging.getLogger(__name__)

LIST_MAX = 200          # newest items listed per kind
TEXT_CAP = 300


@dataclass
class LearnedItem:
    """The common record: what was learned, where it came from, and how it has done."""
    kind: str                 # correction | golden | fix
    id: str                   # the item's key in its own table (fix: the error signature)
    source: str               # that table
    org_id: str
    scope: str                # agent · action type, domain, file kind
    text: str                 # the lesson, pseudonymised
    at: Optional[str]
    used: int = 0
    helped: int = 0
    settled: int = 0
    retired: bool = False
    retired_by: Optional[str] = None
    retired_reason: Optional[str] = None

    @property
    def help_rate(self) -> Optional[float]:
        return round(self.helped / self.settled, 3) if self.settled else None

    def as_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "help_rate": self.help_rate}


async def pseudonymise(org_id: str, value: Any) -> Any:
    """The correction pseudonymiser (personal keys and emails -> keyed labels, credentials masked). KAN-228 makes it
    public as corrections.pseudonymise; until then it is corrections._clean. Same arguments either way."""
    fn = getattr(corrections, "pseudonymise", None) or corrections._clean
    return await fn(org_id, value)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


# ── prompts: retired items are left out, every item put in is recorded as used ─────────────────────────────────────

async def corrections_for_prompt(org_id: str, agent: str, action_type: str, query: str = "", k: int = 3,
                                 also: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """corrections.relevant() without retired items, reason pseudonymised, and each one recorded as used."""
    found = await corrections.relevant(org_id, agent, action_type, query, corrections.TOP_K_MAX, also)
    retired = await loop.retired_ids(org_id, "correction")
    picked = [c for c in found if c["id"] not in retired][:max(1, min(k, corrections.TOP_K_MAX))]
    for c in picked:
        c["reason"] = await pseudonymise(org_id, c.get("reason") or "")
    await loop.record_use(org_id, "correction", [c["id"] for c in picked], scope=f"{agent}:{action_type}")
    return picked


def proposer_scopes(action_type: str, params: Dict[str, Any], requested_by: str) -> List[str]:
    """Every name the proposer of a request may have asked /relevant under (see corrections.agent_of)."""
    names = {corrections.agent_of(params or {}, requested_by), requested_by[:128]}
    names |= {str(params[k])[:128] for k in ("agent", "tool") if isinstance((params or {}).get(k), str)}
    return [f"{n}:{action_type}" for n in names if n]


async def approval_settled(org_id: str, action_type: str, params: Dict[str, Any], requested_by: str,
                           approved: bool, edited: bool) -> int:
    """A request was decided: the corrections shown to its proposer helped when it was approved unchanged."""
    try:
        return await loop.record_outcome(org_id, "correction", approved and not edited,
                                         scopes=proposer_scopes(action_type, params, requested_by))
    except Exception as e:
        logger.warning("learning: approval outcome not recorded: %s", e)
        return 0


async def golden_for_prompt(domain: str, limit: int, org_id: Optional[str], phase: str) -> List[Dict[str, Any]]:
    """get_golden_examples() without this org's retired examples; each one put in is recorded as used in this run."""
    from aether_os.core.learning import golden_retriever
    retired = await loop.retired_ids(org_id, "golden")
    examples = await golden_retriever.get_golden_examples(domain, limit=limit + min(len(retired), 10), org_id=org_id)
    picked = [e for e in examples if e.get("id") not in retired][:limit]
    await loop.record_use(org_id, "golden", [e.get("id") for e in picked], scope=phase, ref=ACTIVE_RUN_ID.get())
    return picked


# ── the shared view ───────────────────────────────────────────────────────────────────────────────────────────────

async def _corrections(s, org_id: str) -> List[LearnedItem]:
    from aether_os.prime.models import PrimeCorrection
    rows = (await s.execute(select(PrimeCorrection).where(PrimeCorrection.org_id == org_id)
                            .order_by(PrimeCorrection.created_at.desc()).limit(LIST_MAX))).scalars().all()
    out = []
    for r in rows:
        lesson = "rejected" if r.corrected.startswith('{"rejected"') else "edited"
        text = await pseudonymise(org_id, f"{lesson}: {r.reason}")
        out.append(LearnedItem("correction", r.id, "prime_corrections", org_id, f"{r.agent} · {r.action_type}",
                               str(text)[:TEXT_CAP], _iso(r.created_at)))
    return out


async def _golden(s, org_id: str) -> List[LearnedItem]:
    from aether_os.core.models import GoldenBuild
    rows = (await s.execute(select(GoldenBuild).where(GoldenBuild.is_active.is_(True),
                                                      GoldenBuild.org_id.in_(("", org_id)))
                            .order_by(GoldenBuild.created_at.desc()).limit(LIST_MAX))).scalars().all()
    return [LearnedItem("golden", r.id, "golden_builds", org_id,
                        f"{r.domain}{' · platform' if not r.org_id else ''}",
                        f"{r.project_name} (rated {r.user_rating or 0:.1f})"[:TEXT_CAP], _iso(r.created_at))
            for r in rows]


async def _fixes(s, org_id: str) -> List[LearnedItem]:
    from aether_os.core.models_memory import FixMemory
    rows = (await s.execute(select(FixMemory).where(FixMemory.org_id == org_id)
                            .order_by(FixMemory.created_at.desc()).limit(LIST_MAX))).scalars().all()
    return [LearnedItem("fix", r.signature, "fix_memory", org_id, r.file_kind or "-",
                        f"{len(r.patches or [])} stored patch(es) for build error {r.signature[:8]}",
                        _iso(r.created_at)) for r in rows]


_LISTERS = {"correction": _corrections, "golden": _golden, "fix": _fixes}


async def learned_items(org_id: str, kinds: Iterable[str] = loop.KINDS) -> Dict[str, List[Dict[str, Any]]]:
    """Per kind: this org's learned items with usage, help rate and retirement."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    async with get_session_factory()() as s:
        for kind in [k for k in kinds if k in _LISTERS]:
            items = await _LISTERS[kind](s, org_id)
            ids = [i.id for i in items]
            usage = {r[0]: r[1:] for r in (await s.execute(
                select(LearningUse.item_id, func.count(),
                       func.sum(case((LearningUse.helped.is_(True), 1), else_=0)),
                       func.count(LearningUse.helped))
                .where(LearningUse.org_id == org_id, LearningUse.kind == kind, LearningUse.item_id.in_(ids))
                .group_by(LearningUse.item_id))).all()} if ids else {}
            states = {r.item_id: r for r in (await s.execute(select(LearningItemState).where(
                LearningItemState.org_id == org_id, LearningItemState.kind == kind,
                LearningItemState.item_id.in_(ids)))).scalars().all()} if ids else {}
            for i in items:
                used, helped, settled = usage.get(i.id, (0, 0, 0))
                i.used, i.helped, i.settled = int(used or 0), int(helped or 0), int(settled or 0)
                st = states.get(i.id)
                if st is not None and st.retired:
                    i.retired, i.retired_by, i.retired_reason = True, st.retired_by, st.retired_reason
            out[kind] = [i.as_dict() for i in items]
    return out


async def item_exists(org_id: str, kind: str, item_id: str) -> bool:
    """The item is one this org can see: its own, or a platform golden example."""
    from aether_os.core.models import GoldenBuild
    from aether_os.core.models_memory import FixMemory
    from aether_os.prime.models import PrimeCorrection
    q = {"correction": select(PrimeCorrection.id).where(PrimeCorrection.org_id == org_id,
                                                         PrimeCorrection.id == item_id),
         "golden": select(GoldenBuild.id).where(GoldenBuild.org_id.in_(("", org_id)), GoldenBuild.id == item_id),
         "fix": select(FixMemory.id).where(FixMemory.org_id == org_id, FixMemory.signature == item_id)}.get(kind)
    if q is None:
        return False
    async with get_session_factory()() as s:
        return (await s.execute(q.limit(1))).first() is not None
