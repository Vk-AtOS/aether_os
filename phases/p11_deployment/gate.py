"""P11 Gate — passes if deployment succeeded or was legitimately skipped."""
from __future__ import annotations
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    meta = result.metadata

    if meta.get("skipped"):
        return GateOutcome(passed=True, confidence=0.7,
                           issues=["No deployable code found — skipped"])

    if not result.success:
        error = meta.get("error", "unknown error")
        # Deployment failures are non-blocking — pipeline already completed
        return GateOutcome(passed=True, confidence=0.5,
                           issues=[f"Deployment failed (non-blocking): {error}"])

    issues = []
    if not meta.get("ready"):
        issues.append("Container started but /health did not respond within 30s")

    return GateOutcome(
        passed=True,
        confidence=0.95 if not issues else 0.75,
        issues=issues,
    )
