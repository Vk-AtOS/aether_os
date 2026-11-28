"""Stage outcome rules: what blocks a run, and which stages an org may switch off.

Kept apart from factory_pipeline.py so the sequential path and the parallel-wave
path apply the same rules.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.models import PhaseConfig, Run
from aether_os.core.security.redact import redact_secrets

logger = logging.getLogger(__name__)

# Stages an org cannot switch off, with the reason recorded when a disable is ignored.
# Everything else in the sequence (s08, s10, s12) produces output no other stage or
# gate reads, and may be skipped.
MANDATORY_STAGES: Dict[str, str] = {
    "s01_intake": "every later stage builds from its requirements",
    "s02_architecture": "all code generation reads its domain model",
    "s03_backend": "the frontend, quality, testing and deploy stages need the backend",
    "s04_frontend": "s05, s06, s09 and s12 read its output; request frontend 'none' to build without a UI",
    "s05_quality": "security and quality review is a blocking check and feeds healing",
    "s06_testing": "healing needs its test summary",
    "s07_healing": "it applies the quality-score gate that decides whether the run may ship",
    "s09_devops": "a run is done only when the deployed app answers at its live URL",
    "s11_handoff": "it produces the quality report and the delivery",
}


def gate_block_reason(stage: str, result: Dict[str, Any],
                      critical_stages: FrozenSet[str]) -> Optional[str]:
    """Why this stage result must end the run, or None if the run may continue.

    "escalated" means the stage's gate still failed after its retries; gates block
    for every stage. A crash or timeout ("failed"/"timeout") blocks for critical
    stages only: the others are allowed to leave a partial deliverable.
    """
    status = result.get("status")
    if status == "escalated":
        issues = "; ".join(str(i) for i in (result.get("issues") or []) if i)
        return f"Stage {stage} did not pass its gate after retries: {issues or 'no reason given'}"
    if status in ("failed", "timeout") and stage in critical_stages:
        return f"Stage {stage} {status}: {result.get('error') or 'no reason given'}"
    return None


def _reason(r: Dict[str, Any]) -> str:
    return str(r.get("error") or "; ".join(str(i) for i in (r.get("issues") or [])[:3] if i) or "no reason given")


def _frontend_blockers(meta: Dict[str, Any]) -> List[str]:
    """The frontend ships only when its production build AND its type-check passed.

    vite does not type-check, and s04 lets a bundle with TypeScript errors through as a warning: the run must still
    not read as completed (completed runs 324a16b7, dca90bef shipped ~10 TS errors each).
    """
    if "build_ok" not in meta and "tsc_errors" not in meta:
        return ["s04_frontend: the production build / type-check result was not recorded"]
    out = []
    if meta.get("build_ok") is False:
        out.append("s04_frontend: the production build failed")
    tsc = int(meta.get("tsc_errors") or 0)
    if tsc:
        first = " | ".join(str(m) for m in (meta.get("tsc_messages") or [])[:2])
        out.append(f"s04_frontend: type-check failed with {tsc} TypeScript error(s)" + (f": {first}" if first else ""))
    return out


def release_blockers(results: Dict[str, Dict[str, Any]]) -> List[str]:
    """Why this run must not be reported "completed"; empty when every required stage really passed (KAN-247).

    A required stage (MANDATORY_STAGES) that is in this run must have passed, and what it says it did not verify
    (metadata["not_verified"]: live tests not run, deploy not attempted, a handoff sub-step failed) counts too.
    The frontend needs a passing build and type-check; failing unit tests that s06 let through need s07 to have
    healed them. A frontend skipped because none was requested is not a blocker.
    """
    out: List[str] = []
    s06_gate = ((results.get("s06_testing") or {}).get("metadata") or {}).get("gate") or {}
    s07_ok = ((results.get("s07_healing") or {}).get("metadata") or {}).get("healing_passed") is True
    for stage in MANDATORY_STAGES:
        r = results.get(stage)
        if r is None:
            continue
        meta = r.get("metadata") or {}
        if stage == "s04_frontend" and meta.get("skipped_reason") == "no_frontend_selected":
            continue
        if stage == "s06_testing" and s06_gate.get("passed") and s07_ok:
            continue  # tests ran; the failures s06 reported are the ones s07 then healed (its pytest passed)
        if r.get("status") != "passed":
            out.append(f"{stage} {r.get('status') or 'did not finish'}: {_reason(r)}")
            continue
        out.extend(f"{stage}: {n}" for n in meta.get("not_verified") or [])
        if stage == "s04_frontend":
            out.extend(_frontend_blockers(meta))
        if stage == "s07_healing" and meta.get("healing_passed") is not True:
            out.append("s07_healing: the app was not verified running")
    if s06_gate.get("tests_failed_but_did_not_block") and not s07_ok:
        out.append(f"s06_testing: {s06_gate.get('tests_failed')} unit test(s) failed and were not healed")
    return out


def final_run_status(results: Dict[str, Dict[str, Any]],
                     council_passed: Optional[bool]) -> Tuple[str, Optional[str]]:
    """(status, message) to store when a run ends: "completed" only if every required stage passed.

    council_passed None = the advisory council produced no verdict (it never upgrades or downgrades by itself).
    """
    blockers = release_blockers(results)
    if blockers:
        more = f" (+{len(blockers) - 5} more)" if len(blockers) > 5 else ""
        return "needs_review", redact_secrets("Not every required stage passed: " + "; ".join(blockers[:5]) + more)
    if council_passed is False:
        return "needs_review", None
    return "completed", None


def summarize_stage_outcomes(results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Run-level summary of the stages that did not complete cleanly.

    Non-critical stages may fail or be skipped without ending the run; this lists
    them so the run result (and the dashboard) never reads as a clean success when
    s06 failed, a stage was switched off, or a stage did not verify what it is for.
    """
    failed: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    for stage, r in results.items():
        status = r.get("status")
        meta = r.get("metadata") or {}
        if status in ("failed", "timeout", "escalated"):
            failed.append({"stage": stage, "status": status, "reason": _reason(r)})
        elif status == "skipped" or meta.get("skipped") is True:
            skipped.append({"stage": stage, "reason": str(meta.get("skipped_reason") or "skipped")})
    # s06's gate lets failing unit tests through (healing repairs them): say so at run level.
    s06_gate = ((results.get("s06_testing") or {}).get("metadata") or {}).get("gate") or {}
    blockers = release_blockers(results)
    return {"failed_stages": failed, "skipped_stages": skipped,
            "all_stages_ok": not failed and not skipped and not blockers,
            "release_blockers": blockers,
            "tests_failed_but_did_not_block": bool(s06_gate.get("tests_failed_but_did_not_block")),
            "tests_not_checked": list(s06_gate.get("not_checked") or [])}


def council_view(council_delivery: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """council_verdict / council_score for the dashboard, from the stored delivery-council result.

    A council that did not run is "unavailable", never "approved" and never "rejected": the
    dashboard reads these two keys and nothing filled them before.
    """
    if not council_delivery:
        return {"council_verdict": None, "council_score": None}
    if council_delivery.get("status") == "unavailable" or council_delivery.get("passed") is None:
        return {"council_verdict": "unavailable", "council_score": None}
    score = council_delivery.get("score")
    return {
        "council_verdict": "approved" if council_delivery.get("passed") else "rejected",
        "council_score": round(score * 100) if isinstance(score, (int, float)) and score <= 1 else score,
    }


def recorded_status(result: Dict[str, Any]) -> str:
    """The status stored on the stage row: what happened, never an upgrade to "completed"."""
    status = result.get("status")
    if status in ("passed", "skipped", "failed", "timeout"):
        return status
    return "failed" if status == "escalated" else "completed"


async def load_disabled_stages(org_id: Optional[str]) -> Set[str]:
    """Stage ids this org has switched off in Settings (phase_configs.enabled = 0).

    If the settings cannot be read, nothing is treated as disabled: running a stage
    the org wanted skipped is the safe direction, silently skipping one is not.
    """
    if not org_id:
        return set()
    try:
        async with get_session_factory()() as session:
            rows = await session.execute(
                select(PhaseConfig.phase_name).where(
                    PhaseConfig.org_id == org_id, PhaseConfig.enabled == 0))
            return {name for (name,) in rows.all()}
    except Exception as exc:
        logger.warning("[stage_gate] could not read stage toggles for org %s; "
                       "running every stage: %s", org_id, exc)
        return set()


def apply_stage_toggles(
    stages: List[str], disabled: Iterable[str],
) -> Tuple[List[str], List[str], Dict[str, str]]:
    """Split `stages` by the org's toggles.

    Returns (stages to run, optional stages to skip, {mandatory stage: why its
    disable was ignored}).
    """
    off = set(disabled)
    skipped = [s for s in stages if s in off and s not in MANDATORY_STAGES]
    ignored = {s: MANDATORY_STAGES[s] for s in stages if s in off and s in MANDATORY_STAGES}
    return [s for s in stages if s not in skipped], skipped, ignored


def timeout_reason(seconds: float, stage: Optional[str] = None) -> str:
    """The reason shown on the run's page after a timeout (redacted; never empty).

    `stage` set: that critical stage did not finish. Not set: the whole build ran past its limit.
    """
    if stage:
        text = (f"Stage {stage} did not finish within {int(seconds)} seconds. "
                "The usual cause is that no model provider is answering: check the model key in Settings.")
    else:
        text = (f"The build did not finish within {int(seconds // 60)} minutes and was stopped. "
                "Either the model provider is slow or not answering (check the model key in Settings), or this build "
                "needs longer than the limit (an operator can raise PIPELINE_TIMEOUT_MINUTES). Then restart the run.")
    return redact_secrets(text)


async def record_run_timeout(ledger: Any, run_id: str, seconds: float) -> str:
    """End a run whose whole-build limit passed: status "timeout" WITH a reason on Run.message.

    The stage it was in (Run.current_phase) is named in the reason. Returns the stored reason.
    """
    stage = None
    try:
        async with get_session_factory()() as session:
            run = await session.get(Run, run_id)
            stage = run.current_phase if run else None
    except Exception as exc:
        logger.warning("[stage_gate] could not read the stage of timed-out run %s: %s", run_id, exc)
    reason = timeout_reason(seconds)
    if stage:
        reason = f"{reason} It was in stage {stage}."
    await ledger.async_update_run_status(run_id, "timeout", message=reason)
    return reason
