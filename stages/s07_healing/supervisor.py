"""
Stage 7: SELF-HEALING
=====================
PURPOSE: The crown jewel of AetherOS. Starts the generated app, probes all
         4 health layers (startup, auth, CRUD, seed data), and autonomously
         repairs any failures using the error registry + deterministic fallbacks.
         Records every repair to generate auto-validators preventing future recurrence.

INPUTS:
  - backend_output_path  : str   — FastAPI src/ to start and heal
  - test_results         : dict  — unit test failures to target (from Stage 6)
  - dimension_critique   : dict  — artifact quality issues to fix (from Stage 5)
  - security_findings    : list  — security issues to patch (from Stage 5)
  - domain_ir            : dict  — entity spec (for deterministic fallback generation)

OUTPUTS:
  - self_healing_report  : dict  — repairs attempted, repairs succeeded, attempts used
  - healing_passed       : bool  — True if app passes all 4 health layers after healing
  - repairs_applied      : list  — list of repair descriptions
  - error_patterns       : list  — new patterns learned and added to error registry
  - auto_validators      : list  — paths to auto-generated validator files

HEALTH LAYERS (probed by QualityMonitor):
  L1: Startup      — app starts on a free port, /health returns 200
  L2: Auth         — POST /auth/login with seed credentials returns access_token
  L3: CRUD         — GET /<entity>/ returns 200 with at least 1 record
  L4: Seed Data    — all entities have ≥10 seed records in the database

REPAIR ATTEMPTS: up to 5 inside p07b (LLM repair, deterministic fallback on the last)
GATE: blocks (ends the run) when the app did not start and answer /health, a spec'd list endpoint returned a 5xx
      or 404, or healing ended with the unit tests still failing (stages/s07_healing/run_verdict.py, KAN-247).
      A static quality score never skips the app start: it can only skip the repair loop when the app then
      starts and answers. The perf / a11y / e2e tests deferred here from s06 run against the started app; any that
      did not run or failed are listed in metadata["not_verified"], which keeps the run from "completed".
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult
from aether_os.stages.s07_healing.run_verdict import decide, httpx_sender, probe_endpoints

logger = logging.getLogger(__name__)

STAGE_CONTRACT = {
    "stage": "s07_healing",
    "display_name": "Self-Healing",
    "critical": False,
    "inputs": [
        "backend_output_path",
        "test_results",
        "dimension_critique",
        "security_findings",
        "domain_ir",
    ],
    "outputs": [
        "self_healing_report",
        "healing_passed",
        "repairs_applied",
        "error_patterns",
        "auto_validators",
    ],
}


class HealingStageSupervisor(PhaseBase):
    """Consolidated supervisor for Stage 7 (Self-Healing).

    Delegates all repair logic to the pre-approved p07b_self_healing task_agent
    (595 lines, already covering the full LLM+deterministic repair loop, quality
    probe L1-L4, and error registry recording).  After healing, it runs
    run_all_validators() to discover any new structural violations and records
    them in the result so downstream stages can track them.
    """

    phase_name = "s07_healing"
    # One gate attempt: the healer already loops up to 5 repair attempts inside run_task, so a gate retry would only
    # repeat that whole loop on the same code (and the quality-gate hook runs this stage up to twice before).
    max_retries = 1

    async def run_task(
        self, phase_input: Any, memory_ctx: List[Dict]
    ) -> TaskResult:
        from aether_os.core.projects import get_project_manager
        from aether_os.phases.p07b_self_healing.task_agent import run as heal_run

        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        # The quality-gate hook (phase_hooks._hook_quality_gate) sets s07_healing_done when the STATIC score
        # reached 80. That may skip the repair loop, never the app start: the shortcut used to return
        # healing_passed=True without starting the app, and 11 of 11 "completed" production runs shipped an app
        # nobody had started (KAN-247). So: start + probe the app; only if that passes is healing skipped.
        _acc = phase_input.input_data if hasattr(phase_input, "input_data") and isinstance(phase_input.input_data, dict) else {}

        async def _live_hook(port: int) -> Dict[str, Any]:
            return await _live_checks(phase_input, memory_ctx, output_dir, port)

        if _acc.get("s07_healing_done") and _unit_tests_green(_acc):
            probe_meta = await _probe_only(phase_input, output_dir, _live_hook)
            if decide(probe_meta)["passed"]:
                logger.info("[s07] static gate passed and the app started and answered: repair loop not needed")
                return _finish(TaskResult(success=True, output_path=str(output_dir), metadata=probe_meta,
                                          confidence=0.9), output_dir, str(phase_input.project_id))
            logger.warning("[s07] static gate passed but the live check failed: running the repair loop")

        # ── Delegate to the pre-approved self-healing engine ──────────────────
        # p07b_self_healing.run() handles:
        #   - Finding main.py + test files in the project directory
        #   - MAX_ATTEMPTS=5 repair loop (LLM → deterministic fallback)
        #   - QualityMonitor L1–L4 probe (startup, auth, CRUD, seed data)
        #   - ErrorRegistry recording + RepairLearning events
        result = await heal_run(phase_input, memory_ctx, output_dir, live_hook=_live_hook)
        if result.metadata is None:
            result.metadata = {}
        _run_validators(result, phase_input)
        return _finish(result, output_dir, str(getattr(phase_input, "project_id", "unknown")))

    async def validate_gate(
        self, result: TaskResult, phase_input: Any
    ) -> GateOutcome:
        # Blocks when the app did not start, a spec'd endpoint failed or healing ended exhausted (KAN-247): this
        # gate used to pass unconditionally, so a run whose app never started still reached "completed". Live
        # tests that did not run or failed do not block; they are listed in metadata["not_verified"] instead.
        verdict = (result.metadata or {}).get("app_verdict") or decide(result.metadata or {})
        if verdict["passed"]:
            return GateOutcome(passed=True, confidence=result.confidence,
                               issues=list(result.issues) + list(verdict["not_verified"]))
        return GateOutcome(passed=False, confidence=result.confidence,
                           issues=[f"s07_healing: {r}" for r in verdict["reasons"]])


# ── Module-level helpers ──────────────────────────────────────────────────────


def _unit_tests_green(ctx: Dict[str, Any]) -> bool:
    """s06's unit tests ran and none failed: only then may a passing static score skip the repair loop."""
    tr = ctx.get("test_results") if isinstance(ctx.get("test_results"), dict) else {}
    return int(tr.get("passed") or 0) > 0 and not int(tr.get("failed") or 0) and not tr.get("collection_error")


async def _probe_only(phase_input: Any, output_dir: Path, live_hook) -> Dict[str, Any]:
    """Start the app and run the live checks without the repair loop; metadata in the healer's shape."""
    import os

    from aether_os.phases.p07b_self_healing import task_agent as heal

    project_dir = Path(os.path.expanduser(f"~/.aether_os/projects/{phase_input.run_id}"))
    raw = (phase_input.input_data or {}).get("entities", [])
    names = [e.get("name", "") if isinstance(e, dict) else str(e) for e in raw or [] if e]
    probe = await heal._quality_probe(project_dir, names, output_dir, live_hook)
    meta = {"success": True, "attempts": 0, "status": "probe_only_after_static_gate", "quality_probe": probe}
    (output_dir / "self_healing.json").write_text(json.dumps(meta, indent=2, default=str))
    return meta


async def _live_checks(phase_input: Any, memory_ctx: List[Dict], output_dir: Path, port: int) -> Dict[str, Any]:
    """Called by the probe while the app runs on `port`: spec'd endpoints first, then perf + a11y + e2e."""
    from aether_os.core.sandbox import phase_exec

    endpoints = await probe_endpoints(phase_exec.app_url(port), (phase_input.input_data or {}).get("entities", []),
                                      httpx_sender, secrets.token_urlsafe(16))
    return {"endpoints": endpoints, "tests": await _run_live_tests(phase_input, memory_ctx, output_dir, port)}


def _run_validators(result: TaskResult, phase_input: Any) -> None:
    """Post-heal static validators: additive, they only append validator_violations."""
    backend_path = ""
    if hasattr(phase_input, "input_data") and isinstance(phase_input.input_data, dict):
        backend_path = phase_input.input_data.get("backend_output_path", "")
    try:
        from aether_os.core.validators import run_all_validators
        if backend_path:
            violations = run_all_validators(backend_path)
            result.metadata["validator_violations"] = violations
            logger.info("s07_healing: post-heal validator found %d violation(s)", len(violations))
    except Exception as exc:
        logger.warning("s07_healing: post-heal validator run failed (non-fatal): %s", exc)


def _record_feedback(result: TaskResult, run_id: str) -> None:
    try:
        from aether_os.core.stage_feedback import record_stage_output, record_stage_fix
        _qp = result.metadata.get("quality_probe", {}) or {}
        record_stage_output("s07_healing", run_id, [], {
            "healing_attempts": float(result.metadata.get("attempts", 0) or 0),
            "fixes_applied": float(len(_qp.get("fixes_applied", []))),
        })
        for _fix in _qp.get("fixes_applied", []):
            record_stage_fix("s07_healing", run_id, str(_fix), "deterministic_fix")
    except Exception as _fb_exc:
        logger.warning("s07_healing: stage_feedback record failed (non-critical): %s", _fb_exc)


def _finish(result: TaskResult, output_dir: Path, run_id: str) -> TaskResult:
    """Stage-level output keys from the healer's metadata, with healing_passed taken from the live verdict.

    The pipeline accumulates these keys into accumulated_context so Stage 8+ read healing_passed directly.
    """
    _record_feedback(result, run_id)
    _meta = result.metadata
    verdict = decide(_meta)
    _qp = _meta.get("quality_probe") or {}
    hook = _qp.get("live_tests") if isinstance(_qp.get("live_tests"), dict) else {}
    _live = hook.get("tests")
    if _live is None:
        _why = (_qp.get("reason") or "app not healthy (L1 failed)") if not _qp.get("l1_passed") else "no live tests"
        _live = {"skipped": True, "reason": f"live tests not run: {_why}"}
        logger.info("s07_healing: %s", _live["reason"])
    _meta.update({
        "healing_passed": verdict["passed"],
        "app_verdict": verdict,
        "not_verified": verdict["not_verified"],
        "repairs_applied": _build_repairs_list(_meta),
        "error_patterns": _qp.get("fixes_applied", []),
        "auto_validators": _collect_validator_paths(output_dir),
        "live_test_results": _live,
        "self_healing_report": {
            "attempts": _meta.get("attempts", 0),
            "status": _meta.get("status", "unknown"),
            "exhausted": _meta.get("self_healing_exhausted", False),
            "quality_probe": _qp,
            "validator_violations": _meta.get("validator_violations", []),
        },
    })
    if not verdict["passed"]:
        result.success = False
        result.issues = list(result.issues or []) + verdict["reasons"]
    return result


async def _run_live_tests(phase_input: Any, memory_ctx: List[Dict], output_dir: Path,
                          port: int) -> Dict[str, Any]:
    """Run perf + a11y + E2E against the live probe app on `port`; return the consolidated dict."""
    import importlib

    from aether_os.stages.s06_testing.supervisor import LIVE_TEST_PHASES, _consolidate_results

    live_input = phase_input.model_copy(update={
        "input_data": {**(phase_input.input_data or {}), "backend_port": port},
    })
    live_dir = output_dir / "live_tests"
    live_dir.mkdir(exist_ok=True)

    async def _one(key: str, module_path: str, fn_name: str) -> TaskResult:
        fn = getattr(importlib.import_module(module_path), fn_name)
        sub = live_dir / key
        sub.mkdir(exist_ok=True)
        return await asyncio.wait_for(fn(live_input, memory_ctx, sub), timeout=150.0)

    raw = await asyncio.gather(*[_one(*t) for t in LIVE_TEST_PHASES], return_exceptions=True)
    results: Dict[str, Any] = {}
    issues: List[str] = []
    for (key, _, _), outcome in zip(LIVE_TEST_PHASES, raw):
        if isinstance(outcome, BaseException):
            logger.warning("s07: live test %s failed (non-critical): %s", key, outcome)
            issues.append(f"{key}: {outcome}")
        else:
            results[key] = outcome
    # json round-trip: the dict is dumped into self_healing.json by the healer
    return json.loads(json.dumps(_consolidate_results(results, issues), default=str))


def _build_repairs_list(meta: Dict[str, Any]) -> List[str]:
    """Extract human-readable repair descriptions from p07b metadata.

    p07b records fixes inside quality_probe.fixes_applied (deterministic patches)
    and implicitly through the attempt count (each attempt after 1 is an LLM repair).
    """
    repairs: List[str] = []

    # Deterministic fixes recorded by quality_probe
    qp_fixes = meta.get("quality_probe", {}).get("fixes_applied", [])
    repairs.extend(qp_fixes)

    # LLM repair attempts: every attempt beyond the first is a repair
    attempts = meta.get("attempts", 1)
    if isinstance(attempts, int) and attempts > 1:
        llm_repairs = attempts - 1
        repairs.append(f"LLM repair attempts: {llm_repairs}")

    # Indicate if deterministic fallback generator was triggered (attempt >= 2)
    if isinstance(attempts, int) and attempts >= 2:
        repairs.append("deterministic_fallback_activated")

    return repairs


def _collect_validator_paths(output_dir: Path) -> List[str]:
    """Return paths to any auto-generated validator files written during healing.

    The repair_learning module may write .py validator files to
    core/validators/auto_generated/.  We surface their paths here so the
    pipeline can track which patterns have been automated away.
    """
    try:
        # Auto-generated validators live in the package, not the output dir
        from aether_os.core.validators.auto_generated import __file__ as _auto_init
        auto_dir = Path(_auto_init).parent
        return [str(p) for p in auto_dir.glob("*.py") if p.name != "__init__.py"]
    except Exception as exc:
        logger.debug("s07_healing: could not list auto-generated validators: %s", exc)
        return []
