"""P11 Gate — validates deployment outcome.

Semantics:
  - skipped: no deployable artefact found → pass with notice
  - success + health ready: full pass
  - success + health timeout: pass with warning (app started but slow)
  - failed: BLOCK — deployment failure must not be silently swallowed;
    the pipeline escalates so the operator can inspect logs
"""
from __future__ import annotations
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    meta = result.metadata

    # ── Legitimately skipped (no Docker, no deployable code) ─────────────────
    if meta.get("skipped"):
        return GateOutcome(
            passed=True,
            confidence=0.7,
            issues=["Deployment skipped — no deployable artefact detected (code-only run)"],
        )

    # ── Deployment actually failed ────────────────────────────────────────────
    if not result.success:
        error = meta.get("error") or "; ".join(result.issues) or "unknown error"
        return GateOutcome(
            passed=False,
            confidence=0.0,
            issues=[
                f"Deployment failed: {error}",
                "Review docker build logs and fix before proceeding",
            ],
        )

    # ── Deployment succeeded ──────────────────────────────────────────────────
    issues: list[str] = []
    confidence = 0.95

    if not meta.get("ready"):
        issues.append("Container started but /health endpoint did not respond within 30s — app may be slow to initialise")
        confidence = 0.75

    url = meta.get("url") or meta.get("live_url")
    if url:
        issues.insert(0, f"Live at {url}")

    return GateOutcome(passed=True, confidence=confidence, issues=issues)
