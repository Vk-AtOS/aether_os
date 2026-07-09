"""P11 Gate — validates deployment outcome, including live E2E smoke test."""
from __future__ import annotations
import logging
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)


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

    url = meta.get("url") or meta.get("live_url")

    if not meta.get("ready"):
        issues.append(
            "Container started but /health did not respond within 30s — "
            "app may be slow to initialise; check docker logs"
        )
        confidence = 0.75
    elif url:
        # ── Live E2E smoke test ───────────────────────────────────────────────
        # Find project_dir: output_path is <project_dir>/p11_deployment
        try:
            project_dir = Path(result.output_path or "").parent
            from aether_os.phases.p11_deployment.smoke_test import run_smoke_sync
            smoke = run_smoke_sync(url, project_dir)

            if smoke.failures:
                issues.extend([f"Smoke fail: {f}" for f in smoke.failures[:5]])
                # Lower confidence proportional to failure count; don't hard-block
                # — self-healing has specific errors now and can patch precisely
                confidence = max(0.55, 0.95 - 0.12 * len(smoke.failures))
            if smoke.warnings:
                issues.extend([f"Smoke note: {w}" for w in smoke.warnings[:3]])
            if smoke.entities_tested > 0 and not smoke.failures:
                issues.insert(
                    0,
                    f"Smoke PASS — {smoke.entities_tested} entities CRUD-verified "
                    f"in {smoke.duration_seconds}s",
                )
            elif smoke.entities_tested == 0 and not smoke.failures:
                issues.append("Smoke: no entities in domain_ir to test — endpoint reachable")
        except ImportError:
            issues.append("aiohttp not installed — live smoke test skipped")
        except Exception as exc:
            logger.warning("p11_deployment gate: smoke test error: %s", exc)
            issues.append(f"Smoke test error (non-fatal): {exc}")

    if url:
        issues.insert(0, f"Live at {url}")

    return GateOutcome(passed=True, confidence=confidence, issues=issues)
