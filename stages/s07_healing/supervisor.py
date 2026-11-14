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

REPAIR ATTEMPTS: up to 3 (attempt 1 = LLM repair, attempt 2+ = deterministic fallback)
CRITICAL: No — pipeline continues even if healing fails (handoff includes failure report)
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult

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

    async def run_task(
        self, phase_input: Any, memory_ctx: List[Dict]
    ) -> TaskResult:
        from aether_os.core.projects import get_project_manager
        from aether_os.phases.p07b_self_healing.task_agent import run as heal_run

        pm = get_project_manager()
        output_dir = pm.get_output_dir(phase_input.project_id, self.phase_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        # WL2: if the quality-gate hook already ran healing successfully (triggered
        # from phase_hooks._hook_quality_gate after p07_testing), skip re-running the
        # full repair loop to avoid a double-heal race where whichever pass runs last
        # wins with no explicit reconciliation.  Run validate_gate() only instead.
        _acc = phase_input.input_data if hasattr(phase_input, "input_data") and isinstance(phase_input.input_data, dict) else {}
        if _acc.get("s07_healing_done"):
            _prior = _acc.get("s07_healing_result", {})
            logger.info(
                "[s07] healing already completed via quality gate hook (score=%.1f, attempt=%s) "
                "— running final validation only",
                _prior.get("score", 0.0),
                _prior.get("attempt", "?"),
            )
            return TaskResult(
                success=True,
                output_path=str(output_dir),
                metadata={
                    "skipped": True,
                    "live_test_results": {"skipped": True, "reason": "live tests not run: already healed via gate hook"},
                    "healing_passed": True,
                    "repairs_applied": [],
                    "error_patterns": [],
                    "auto_validators": [],
                    "self_healing_report": {
                        "attempts": 0,
                        "status": "skipped_already_healed",
                        "exhausted": False,
                        "quality_probe": {},
                        "validator_violations": [],
                    },
                    "skipped_reason": "already_healed_via_gate",
                    "prior_result": _prior,
                },
                issues=[],
                confidence=1.0,
            )

        # ── Delegate to the pre-approved self-healing engine ──────────────────
        # p07b_self_healing.run() handles:
        #   - Finding main.py + test files in the project directory
        #   - MAX_ATTEMPTS=5 repair loop (LLM → deterministic fallback)
        #   - QualityMonitor L1–L4 probe (startup, auth, CRUD, seed data)
        #   - ErrorRegistry recording + RepairLearning events
        async def _live_hook(port: int) -> Dict[str, Any]:
            return await _run_live_tests(phase_input, memory_ctx, output_dir, port)

        result = await heal_run(phase_input, memory_ctx, output_dir, live_hook=_live_hook)

        # ── Post-heal: run static validators to surface structural violations ──
        # This is additive — it never overwrites the repair result, only appends
        # a validator_violations key so downstream stages can surface them.
        backend_path = ""
        if hasattr(phase_input, "input_data") and isinstance(phase_input.input_data, dict):
            backend_path = phase_input.input_data.get("backend_output_path", "")
        try:
            from aether_os.core.validators import run_all_validators
            if backend_path:
                violations = run_all_validators(backend_path)
                if result.output and isinstance(result.metadata, dict):
                    result.metadata["validator_violations"] = violations
                    logger.info(
                        "s07_healing: post-heal validator found %d violation(s)",
                        len(violations),
                    )
        except Exception as exc:
            logger.warning("s07_healing: post-heal validator run failed (non-fatal): %s", exc)

        # ── Record stage feedback for learning tracker ────────────────────────
        try:
            from aether_os.core.stage_feedback import record_stage_output, record_stage_fix
            _run_id = str(getattr(phase_input, "project_id", "unknown"))
            _heal_meta = result.metadata or {}
            _qp = _heal_meta.get("quality_probe", {})
            _quality_scores = {
                "healing_attempts": float(_heal_meta.get("attempts", 0)),
                "fixes_applied": float(len(_qp.get("fixes_applied", []))),
            }
            record_stage_output("s07_healing", _run_id, [], _quality_scores)
            # Record each deterministic fix as a stage_fix event
            for _fix in _qp.get("fixes_applied", []):
                record_stage_fix("s07_healing", _run_id, str(_fix), "deterministic_fix")
        except Exception as _fb_exc:
            logger.warning("s07_healing: stage_feedback record failed (non-critical): %s", _fb_exc)

        # ── Enrich metadata with stage-level output keys ──────────────────────
        # The pipeline accumulates these keys into accumulated_context so Stage 8+
        # can read healing_passed without parsing the raw self_healing.json file.
        _meta = result.metadata or {}
        _healing_passed = (
            _meta.get("status") == "all_tests_passing"
            and not _meta.get("self_healing_exhausted", False)
        )
        _repairs_applied = _build_repairs_list(_meta)
        _auto_validators = _collect_validator_paths(output_dir)

        result.metadata.update({
            "healing_passed": _healing_passed,
            "repairs_applied": _repairs_applied,
            "error_patterns": _meta.get("quality_probe", {}).get("fixes_applied", []),
            "auto_validators": _auto_validators,
            "self_healing_report": {
                "attempts": _meta.get("attempts", 0),
                "status": _meta.get("status", "unknown"),
                "exhausted": _meta.get("self_healing_exhausted", False),
                "quality_probe": _meta.get("quality_probe", {}),
                "validator_violations": _meta.get("validator_violations", []),
            },
        })

        # ── Post-heal live tests (perf + a11y + E2E) ─────────────────────────
        # They ran inside the probe (the app only lives there); record why if not.
        _qp = _meta.get("quality_probe") or {}
        _live = _qp.get("live_tests")
        if _live is None:
            _why = (_qp.get("reason") or "app not healthy (L1 failed)") if not _qp.get("l1_passed") else "no live tests"
            _live = {"skipped": True, "reason": f"live tests not run: {_why}"}
            logger.info("s07_healing: %s", _live["reason"])
        result.metadata["live_test_results"] = _live

        return result

    async def validate_gate(
        self, result: TaskResult, phase_input: Any
    ) -> GateOutcome:
        # Gate always passes — even a failed healing run is non-critical.
        # The healing_passed flag lets downstream stages adapt their behaviour.
        return GateOutcome(
            passed=True,
            confidence=result.confidence,
            issues=result.issues,
        )


# ── Module-level helpers ──────────────────────────────────────────────────────


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
