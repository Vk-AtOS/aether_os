"""KAN-188: the deterministic output-quality gate (scripts/ci/quality_gate.py) holds on main and catches a drop."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("quality_gate", ROOT / "scripts" / "ci" / "quality_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def test_scores_match_the_stored_baseline():
    scores = gate.score_all()
    assert gate.compare(scores, json.loads(gate.BASELINE.read_text())) == []


def test_good_fixtures_outscore_weak_ones():
    s = gate.score_all()
    assert s["good_router.py"] > s["weak_router.py"] and s["GoodPage.tsx"] > s["WeakPage.tsx"]
    assert s["GoodPage.tsx"] > 0.9  # a 0.0 means the critic could not read the fixture, not a quality result


def test_a_drop_below_baseline_fails_and_a_gain_does_not():
    base = {"a.py": 0.9}
    assert gate.compare({"a.py": 0.9 - gate.TOLERANCE - 0.01}, base)
    assert gate.compare({"a.py": 0.95}, base) == []
    assert gate.compare({}, base) == ["a.py: fixture missing"]
