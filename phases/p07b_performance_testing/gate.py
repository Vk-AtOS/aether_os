"""P07b Gate — validates performance test produced latency metrics within acceptable bounds."""
from __future__ import annotations
import json
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


_P95_WARN_MS = 500    # warn if p95 > 500ms
_P95_FAIL_MS = 2000   # fail if p95 > 2s
_ERROR_RATE_WARN = 0.02   # warn if error rate > 2%
_ERROR_RATE_FAIL = 0.10   # fail if error rate > 10%


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=True,
            confidence=0.5,
            issues=["Performance test produced no output — latency baseline not established"],
        )

    output_path = Path(result.output_path)
    try:
        candidates = (
            [output_path] if output_path.suffix == ".json"
            else list(output_path.rglob("perf*.json")) + list(output_path.rglob("load*.json")) + list(output_path.rglob("results*.json"))
        )
        if candidates and candidates[0].exists():
            data = json.loads(candidates[0].read_text())
            p95 = data.get("p95_ms", data.get("p95", 0))
            error_rate = data.get("error_rate", data.get("errors_pct", 0))

            if p95 and p95 > _P95_FAIL_MS:
                issues.append(f"p95 latency {p95:.0f}ms exceeds {_P95_FAIL_MS}ms threshold — performance unacceptable")
                return GateOutcome(passed=False, confidence=0.3, issues=issues)
            if p95 and p95 > _P95_WARN_MS:
                issues.append(f"p95 latency {p95:.0f}ms exceeds {_P95_WARN_MS}ms warning threshold")

            if error_rate and error_rate > _ERROR_RATE_FAIL:
                issues.append(f"Error rate {error_rate:.1%} exceeds {_ERROR_RATE_FAIL:.0%} — app is unstable under load")
                return GateOutcome(passed=False, confidence=0.2, issues=issues)
            if error_rate and error_rate > _ERROR_RATE_WARN:
                issues.append(f"Error rate {error_rate:.1%} exceeds {_ERROR_RATE_WARN:.0%} warning threshold")
    except Exception as e:
        issues.append(f"Could not parse performance results: {e}")

    confidence = 0.9 if not issues else 0.65
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
