#!/usr/bin/env python3
"""Deterministic output-quality regression gate (KAN-188).

Scores the golden fixtures in tests/fixtures/quality_golden/ with the same critic that scores generated
projects (core/quality/dimension_critic.py, pattern scoring only: no model, no network, no npm) and compares
each score with benchmarks/quality_baseline.json. Exit 1 when any fixture drops more than TOLERANCE below its
baseline, or when a fixture is missing. A score going UP is reported, not a failure: raise the baseline on purpose.

  python scripts/ci/quality_gate.py                    check against the baseline
  python scripts/ci/quality_gate.py --write-baseline   accept the current scores as the new baseline
  python scripts/ci/quality_gate.py --out FILE         also write the scores as JSON (used by the weekly workflow)

The checkout must be importable as `aether_os` (PYTHONPATH=<parent dir>), like scripts/ci/check_docs.py.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "quality_golden"
BASELINE = ROOT / "benchmarks" / "quality_baseline.json"
TOLERANCE = 0.02


def score_all() -> dict[str, float]:
    from aether_os.core.quality.dimension_critic import critique_artifact

    scores = {}
    for f in sorted(p for p in FIXTURES.iterdir() if p.suffix in (".py", ".tsx")):
        scores[f.name] = critique_artifact(str(f), root=str(FIXTURES)).overall_score
    return scores


def compare(scores: dict[str, float], baseline: dict[str, float]) -> list[str]:
    problems = []
    for name, base in baseline.items():
        if name not in scores:
            problems.append(f"{name}: fixture missing")
        elif scores[name] < base - TOLERANCE:
            problems.append(f"{name}: score {scores[name]:.4f} fell below baseline {base:.4f} (tolerance {TOLERANCE})")
    for name in sorted(scores.keys() - baseline.keys()):
        problems.append(f"{name}: no baseline (run --write-baseline)")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()
    scores = score_all()
    if args.out:
        Path(args.out).write_text(json.dumps(scores, indent=2, sort_keys=True) + "\n")
    if args.write_baseline:
        BASELINE.write_text(json.dumps(scores, indent=2, sort_keys=True) + "\n")
        print(f"baseline written: {scores}")
        return 0
    for name, s in scores.items():
        print(f"{name}: {s:.4f}")
    problems = compare(scores, json.loads(BASELINE.read_text()))
    for p in problems:
        print("FAIL", p)
    print(f"quality_gate: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
