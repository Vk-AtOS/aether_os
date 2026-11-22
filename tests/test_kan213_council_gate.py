"""KAN-213: council gating, verdict reuse, unavailable-review handling, prompt prefix."""
from dataclasses import dataclass, field
from typing import List

import pytest

from aether_os.core.council import council_gate as g


@dataclass
class _R:
    score: int


@dataclass
class _Report:
    reviews: List[_R] = field(default_factory=list)


GOOD = {"main.py": "x = 1\n", "crud.py": "y = 2\n"}


@pytest.fixture(autouse=True)
def _clear():
    g._verdicts.clear()
    g._calls.clear()


def _counter(report):
    calls = []

    async def fn():
        calls.append(1)
        return report

    return fn, calls


@pytest.mark.asyncio
async def test_not_called_while_cheap_checks_fail():
    fn, calls = _counter(_Report([_R(8)]))
    report, status = await g.gated_review("r1", {"main.py": "def (:\n"}, fn)
    assert status == g.SKIPPED_CHECKS and report is None and calls == []
    assert g.calls_for("r1") == 0


@pytest.mark.asyncio
async def test_unchanged_files_reuse_verdict_and_changed_files_recall():
    fn, calls = _counter(_Report([_R(8)]))
    _, s1 = await g.gated_review("r2", GOOD, fn)
    _, s2 = await g.gated_review("r2", dict(GOOD), fn)
    assert (s1, s2) == (g.REVIEWED, g.CACHED) and len(calls) == 1
    _, s3 = await g.gated_review("r2", {**GOOD, "crud.py": "y = 3\n"}, fn)
    assert s3 == g.REVIEWED and len(calls) == 2 and g.calls_for("r2") == 2


@pytest.mark.asyncio
async def test_zero_score_from_no_reviewers_is_unavailable_not_cached():
    fn, calls = _counter(_Report([]))
    report, status = await g.gated_review("r3", GOOD, fn)
    assert status == g.UNAVAILABLE and report.reviews == []
    await g.gated_review("r3", GOOD, fn)
    assert len(calls) == 2  # an unavailable review is not cached as a verdict


@pytest.mark.asyncio
async def test_empty_input_is_unavailable_without_a_call():
    fn, calls = _counter(_Report([_R(9)]))
    _, status = await g.gated_review("r4", {"main.py": "  \n"}, fn)
    assert status == g.UNAVAILABLE and calls == []
