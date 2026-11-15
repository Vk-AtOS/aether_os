"""
AetherOS — Post-pipeline artifact collection helpers.
Extracted from factory_pipeline.py. These are free async functions that
accept all needed context as arguments so they can be scheduled as
asyncio tasks by the pipeline after all phases complete.
"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Dict, Optional
from aether_os.core.artifact_store import get_artifact_store
from aether_os.core.run_app import safe_fs
from aether_os.core.artifact_store import get_artifact_store as _gas_s3
from aether_os.core.audit.ledger import get_ledger
from aether_os.core.council import DeliveryCouncil
from aether_os.core.db import get_session_factory as _gsf
from aether_os.core.db import get_session_factory as _gsf_cn
from aether_os.core.db import get_session_factory as _gsf_l
from aether_os.core.models import GlobalPattern as _GP
from aether_os.core.models import Notification as _Notif_cn
from aether_os.core.models import Run as _Run
from aether_os.core.pipeline_state import get_control
from aether_os.orchestrator.events import publish_event  # redacts error text
from aether_os.core.services import learning_service as _ls
from aether_os.core.services.memory_service import get_memory_service
from aether_os.orchestrator.messages import PhaseInput
from aether_os.orchestrator.phase_sequence import _load_supervisor
from aether_os.orchestrator.run_state import _extract_project_name
from sqlalchemy import select as _sel_l
from sqlalchemy import update as _sa_update
import asyncio
import time
logger = logging.getLogger(__name__)
async def embed_artifacts(
    run_id: str,
    project_dir: Path,
    results: Dict,
    org_id: Optional[str],
) -> None:
    """Embed produced source files into the artifact store for semantic search."""
    if await get_control(run_id) == "cancel":
        return
    try:
        store = get_artifact_store()
        _extensions = {".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".sql"}
        _count = 0
        _errors = 0
        _MAX_ARTIFACTS = int(os.environ.get("ARTIFACT_EMBED_LIMIT", "5000"))
        _total_files = 0
        for _phase in results:
            if await get_control(run_id) == "cancel":
                break
            if safe_fs.is_real_dir(project_dir, _phase):   # a symlinked phase folder is skipped
                for f in safe_fs.walk_files(project_dir, _phase):   # f is relative to project_dir
                    if f.suffix in _extensions:
                        _total_files += 1
                        try:
                            _text = safe_fs.read_text_or_none(project_dir, f)
                            if _text is None:
                                continue
                            await store.store_artifact(run_id, str(f), _text, org_id=org_id)
                            _count += 1
                            if _count >= _MAX_ARTIFACTS:
                                break
                        except Exception as _ef:
                            _errors += 1
                            logger.debug("[pipeline] artifact embed failed %s: %s", f.name, _ef)
                            continue
            if _count >= _MAX_ARTIFACTS:
                break
        if _count >= _MAX_ARTIFACTS:
            _skipped = _total_files - _count
            logger.warning(
                "[pipeline] Semantic search indexed %d of %d files — %d were skipped due to volume limits (ARTIFACT_EMBED_LIMIT=%d) for run %s.",
                _count, _total_files, _skipped, _MAX_ARTIFACTS, run_id,
            )
            await publish_event(run_id, {
                "type": "artifact_embed_truncated",
                "limit": _MAX_ARTIFACTS,
                "indexed": _count,
                "total": _total_files,
                "skipped": _skipped,
                "run_id": run_id,
                "message": f"Semantic search indexed {_count} of {_total_files} files — {_skipped} were skipped due to volume limits.",
            })
        if _errors:
            logger.warning("[pipeline] Embedded %d artifacts (%d failed) for run %s", _count, _errors, run_id)
        else:
            logger.info("[pipeline] Embedded %d artifacts for run %s", _count, run_id)
    except Exception as e:
        logger.warning("[pipeline] Artifact embedding skipped: %s", e)
async def upload_to_s3(
    run_id: str,
    project_dir: Path,
) -> None:
    """Upload all run artifacts to S3 for durable storage."""
    if await get_control(run_id) == "cancel":
        return
    try:
        _s3_count = await _gas_s3().upload_run_to_s3(run_id, project_dir)
        if _s3_count:
            await publish_event(run_id, {
                "type": "s3_upload_complete",
                "run_id": run_id,
                "count": _s3_count,
            })
    except Exception as _s3_exc:
        logger.warning("[pipeline] S3 upload skipped: %s", _s3_exc)
# Mapping from DeliveryCouncil criterion name → STAGE(s) to re-run (the keys of
# phase_sequence.PHASE_SUPERVISORS: the old p06_/p07_/p10_ ids were retired, so
# _load_supervisor found nothing and remediation never re-ran anything).
_CRITERION_TO_PHASES = {
    "security":     ["s05_quality"],
    "testing":      ["s06_testing", "s07_healing"],
    "quality":      ["s06_testing", "s07_healing"],
    "frontend":     ["s04_frontend"],
    "completeness": ["s04_frontend", "s11_handoff"],
    "docs":         ["s11_handoff"],
}
async def _run_council_remediation_phases(
    run_id: str,
    failing_criteria: list,
    accumulated_context: Dict,
    council_reason: str,
) -> None:
    """
    Re-run only the phases that own the failing council criteria.
    This is called at most once per pipeline run (guarded by _council_retry_count
    in accumulated_context).  Injects the council critique as context so each
    re-run phase knows what to fix.
    """
    run_id_str = run_id
    # Deduplicate phases while preserving dependency order
    seen: set = set()
    phases_to_rerun = []
    for criterion in failing_criteria:
        for phase in _CRITERION_TO_PHASES.get(criterion, []):
            if phase not in seen:
                seen.add(phase)
                phases_to_rerun.append(phase)
    if not phases_to_rerun:
        logger.info("[council_remediation] No remediable phases for criteria: %s", failing_criteria)
        return
    logger.info(
        "[council_remediation] Re-running %d phase(s) for failing criteria %s: %s",
        len(phases_to_rerun), failing_criteria, phases_to_rerun,
    )
    # Inject council critique so re-run phases know what to fix
    remediation_context = dict(accumulated_context)
    remediation_context["council_critique"] = (
        f"DeliveryCouncil identified failures in: {', '.join(failing_criteria)}. "
        f"Reason: {council_reason}. "
        "Please address the above issues in this re-run."
    )
    remediation_context["is_council_remediation"] = True
    project_dir_str = accumulated_context.get("project_dir", "")
    domain = accumulated_context.get("domain", "general")
    client_id = accumulated_context.get("client_id", "system")
    for phase_name in phases_to_rerun:
        supervisor = _load_supervisor(phase_name)
        if not supervisor:
            logger.warning("[council_remediation] No supervisor for phase %r — skipping", phase_name)
            continue
        phase_input = PhaseInput(
            run_id=run_id_str,
            project_id=run_id_str,
            phase=phase_name,
            input_data=remediation_context,
            output_dir=project_dir_str,
            domain=domain,
            client_id=client_id,
        )
        start_t = time.time()
        try:
            task_result = await asyncio.wait_for(
                supervisor.run(phase_input),
                timeout=600,
            )
            dur = round(time.time() - start_t, 2)
            logger.info(
                "[council_remediation] %s re-run complete in %.1fs success=%s",
                phase_name, dur, task_result.success,
            )
        except asyncio.TimeoutError:
            logger.warning("[council_remediation] %s re-run timed out after 600s", phase_name)
        except Exception as _re_exc:
            logger.warning("[council_remediation] %s re-run failed: %s", phase_name, _re_exc)
async def _persist_run_status(run_id: str, delivery: Dict, council_passed: bool) -> None:
    """Persist council_delivery and final status to the Run record."""
    _council_score = delivery.get("score", 1.0)
    _final_status = "completed" if council_passed else "needs_review"
    try:
        async with _gsf()() as _s:
            await _s.execute(
                _sa_update(_Run)
                .where(_Run.id == run_id)
                .values(
                    council_delivery=delivery,
                    status=_final_status,
                    message=(
                        None if council_passed
                        else f"DeliveryCouncil flagged issues (score={_council_score:.2f}): "
                             f"{delivery.get('reason', '')} — "
                             f"Suggestions: {'; '.join(delivery.get('suggestions', []))}"
                    ),
                )
            )
            await _s.commit()
    except Exception as _db_exc:
        logger.warning("[council] Failed to persist run status for %s: %s", run_id, _db_exc)
async def delivery_council_check(
    run_id: str,
    project_name: Optional[str],
    raw_input: str,
    domain: str,
    results: Dict,
    org_id: Optional[str],
    accumulated_context: Dict,
) -> None:
    """
    Run the DeliveryCouncil check and persist the final run status.
    If score < 0.5 on the first evaluation AND this is the first council
    check (guard: _council_retry_count not set), we:
      1. Identify which criteria failed (from criteria_failures in the response)
      2. Re-run the phases that own those criteria (once, max 1 cycle)
      3. Run the council again — if it still fails, mark as needs_review
    """
    async def _run_council(phases_results: Dict) -> Dict:
        _dc = DeliveryCouncil()
        return await asyncio.wait_for(
            _dc.run(
                run_id=run_id,
                project_name=project_name or accumulated_context.get("project_name") or _extract_project_name(raw_input, run_id),
                domain=domain,
                phases_results=phases_results,
                org_id=org_id,
            ),
            timeout=120,
        )
    async def _send_council_fail_notification(score: float, reason: str) -> None:
        """Fire in-app notification on council_score < 0.5 — non-blocking."""
        if not (score < 0.5 and org_id):
            return
        try:
            _pname_cn = project_name or f"run-{run_id[:8]}"
            _notif_cn = _Notif_cn(
                org_id=org_id,
                type="council_fail",
                title=f"Council failed for {_pname_cn}",
                message=f"DeliveryCouncil score {score:.2f} < 0.5: {reason}",
                link=f"/dashboard/runs/{run_id}",
            )
            async with _gsf_cn()() as _s_cn:
                _s_cn.add(_notif_cn)
                await _s_cn.commit()
        except Exception as _ne_cn:
            logger.debug("[pipeline] council_fail notification failed: %s", _ne_cn)
    try:
        # ── First council evaluation ──────────────────────────────────────────
        _delivery = await _run_council(results)
        _council_passed = _delivery.get("passed", False)
        _council_score = _delivery.get("score", 1.0)
        _criteria_failures = _delivery.get("criteria_failures") or []
        logger.info(
            "DeliveryCouncil [pass 1]: run=%s passed=%s score=%.2f criteria_failures=%s reason=%s",
            run_id, _council_passed, _council_score, _criteria_failures, _delivery.get("reason", ""),
        )
        # ── Targeted phase re-runs when score < 0.5 (first evaluation only) ──
        # Guard: _council_retry_count prevents re-entering this block on the
        # second council evaluation triggered by our own remediation re-runs.
        _retry_count = accumulated_context.get("_council_retry_count", 0)
        if not _council_passed and _council_score < 0.5 and _retry_count == 0 and _criteria_failures:
            logger.info(
                "DeliveryCouncil: score %.2f < 0.5 with remediable criteria %s — "
                "triggering targeted phase re-runs for run %s",
                _council_score, _criteria_failures, run_id,
            )
            await publish_event(run_id, {
                "type": "council_remediation_start",
                "run_id": run_id,
                "criteria_failures": _criteria_failures,
                "score": _council_score,
            })
            # Mark that we have started remediation (guard against infinite loop)
            accumulated_context["_council_retry_count"] = 1
            # Re-run phases that own the failing criteria
            await _run_council_remediation_phases(
                run_id=run_id,
                failing_criteria=_criteria_failures,
                accumulated_context=accumulated_context,
                council_reason=_delivery.get("reason", ""),
            )
            # ── Second council evaluation (post-remediation) ──────────────────
            logger.info("DeliveryCouncil [pass 2]: evaluating post-remediation results for run %s", run_id)
            try:
                _delivery2 = await _run_council(results)
                _council_passed = _delivery2.get("passed", False)
                _council_score = _delivery2.get("score", _council_score)
                _delivery = _delivery2  # use second result for final persistence
                logger.info(
                    "DeliveryCouncil [pass 2]: run=%s passed=%s score=%.2f reason=%s",
                    run_id, _council_passed, _council_score, _delivery.get("reason", ""),
                )
            except Exception as _dc2_exc:
                logger.warning(
                    "DeliveryCouncil [pass 2] failed for run %s — using pass-1 result: %s",
                    run_id, _dc2_exc,
                )
            await publish_event(run_id, {
                "type": "council_remediation_complete",
                "run_id": run_id,
                "score_after": _council_score,
                "passed": _council_passed,
            })
        # ── Persist final status ──────────────────────────────────────────────
        await _persist_run_status(run_id, _delivery, _council_passed)
        if not _council_passed:
            logger.warning(
                "DeliveryCouncil: run %s flagged as needs_review (score=%.2f): %s | suggestions: %s",
                run_id, _council_score, _delivery.get("reason", ""),
                _delivery.get("suggestions", []),
            )
            await publish_event(run_id, {
                "type": "council_delivery_review",
                "passed": False,
                "score": _council_score,
                "reason": _delivery.get("reason", ""),
                "suggestions": _delivery.get("suggestions", []),
            })
            await _send_council_fail_notification(_council_score, _delivery.get("reason", ""))
        else:
            logger.info("DeliveryCouncil: run %s passed (score=%.2f)", run_id, _council_score)
            await publish_event(run_id, {
                "type": "council_delivery_passed",
                "passed": True,
                "score": _council_score,
                "status": "completed",
            })
    except asyncio.TimeoutError:
        logger.warning("DeliveryCouncil timed out after 120s for run %s — recorded as unavailable", run_id)
        await _record_council_unavailable(run_id, "council_timeout", org_id, project_name)
    except Exception as _exc:
        logger.warning("DeliveryCouncil check failed: %s", _exc)
        await _record_council_unavailable(run_id, "council_error", org_id, project_name)
async def _record_council_unavailable(
    run_id: str, note: str, org_id: Optional[str] = None, project_name: Optional[str] = None,
) -> None:
    """The delivery council did not produce a verdict (timeout/error).

    It is advisory, so the run keeps its status, but the missing verdict is never reported
    as a pass: it is stored on the run (council_delivery.status == "unavailable", visible in
    the run data), announced with its own event, written to the audit ledger and sent to the
    org as an in-app notification: a delivery nobody independently reviewed must not go unnoticed.
    """
    verdict = {
        "status": "unavailable", "passed": None, "score": None, "advisory": True,
        "reason": note, "suggestions": [],
    }
    try:
        async with _gsf()() as _s:
            await _s.execute(
                _sa_update(_Run).where(_Run.id == run_id)
                .values(council_delivery=verdict, status="completed",
                        message="DeliveryCouncil did not run (" + note + ") - delivery was not independently reviewed")
            )
            await _s.commit()
    except Exception as _db_exc:
        logger.warning("[council] Could not record unavailable verdict for run %s: %s", run_id, _db_exc)
    await publish_event(run_id, {
        "type": "council_delivery_unavailable",
        "passed": None,
        "status": "completed",
        "note": note,
    })
    if not org_id:
        return
    try:
        await get_ledger().async_log_audit_event(
            org_id=org_id, user_id="system", action="council_delivery_unavailable",
            resource_type="run", resource_id=run_id, metadata={"note": note},
        )
    except Exception as _led_exc:  # the ledger never raises, this guards the import/lookup only
        logger.warning("[council] ledger entry for unavailable council failed (run %s): %s", run_id, _led_exc)
    try:
        async with _gsf_cn()() as _s_cn:
            _s_cn.add(_Notif_cn(
                org_id=org_id, type="council_unavailable",
                title=f"Delivery review did not run for {project_name or 'run-' + run_id[:8]}",
                message=f"The delivery council produced no verdict ({note}); the build was not independently reviewed.",
                link=f"/dashboard/runs/{run_id}",
            ))
            await _s_cn.commit()
    except Exception as _ne_cn:
        logger.warning("[council] notification for unavailable council failed (run %s): %s", run_id, _ne_cn)
async def store_run_memory(
    run_id: str,
    org_id: Optional[str],
    raw_input: str,
    domain: str,
    results: Dict,
) -> None:
    """Store run outcome in cross-run memory service for future learning."""
    if not org_id:
        return
    try:
        ms = get_memory_service()
        await ms.store_run_outcome(
            org_id=org_id,
            run_id=run_id,
            raw_input=raw_input,
            status="completed",
            domain=domain,
            phase_outputs={k: v.get("artifacts", {}) for k, v in results.items()},
        )
    except Exception as _me:
        logger.debug("[pipeline] Memory store skipped: %s", _me)
async def extract_learning(
    run_id: str,
    org_id: Optional[str],
    client_id: Optional[str],
    domain: str,
    results: Dict,
    accumulated_context: Dict,
) -> None:
    """Extract and persist per-user and global learning patterns after pipeline completion."""
    if not org_id or not client_id:
        return
    try:
        async with _gsf_l()() as _sl:
            _run_tech = accumulated_context.get("architecture_json", {}).get("tech_stack", {})
            if _run_tech:
                await _ls.upsert_pattern(
                    org_id, client_id, "tech_stack", "preferred_stack",
                    {"stack": _run_tech, "domain": domain}, run_id, _sl,
                )
            if domain and domain != "general":
                await _ls.upsert_pattern(
                    org_id, client_id, "domain_expertise", domain,
                    {"domain": domain, "run_id": run_id}, run_id, _sl,
                )
            _q_flag = None
            for _ph in results.values():
                if isinstance(_ph, dict) and "test_quality_flag" in _ph:
                    _q_flag = _ph["test_quality_flag"]
            if _q_flag:
                await _ls.upsert_pattern(
                    org_id, client_id, "deployment_preference", "last_successful_deploy",
                    {"status": "completed", "quality": _q_flag, "domain": domain}, run_id, _sl,
                )
            _stack_key = str(_run_tech.get("backend", domain or "unknown"))
            _existing_gp = (await _sl.execute(
                _sel_l(_GP).where(
                    _GP.org_id == org_id,
                    _GP.domain == domain,
                    _GP.pattern_name == _stack_key,
                )
            )).scalar_one_or_none()
            _q_score = 0.7 if _q_flag == "pass" else (0.4 if _q_flag == "warn" else 0.2)
            if _existing_gp:
                _existing_gp.usage_count += 1
                _existing_gp.avg_quality_score = round(
                    (_existing_gp.avg_quality_score * (_existing_gp.usage_count - 1) + _q_score)
                    / _existing_gp.usage_count, 3
                )
                _existing_gp.success_rate = round(
                    (_existing_gp.success_rate * (_existing_gp.usage_count - 1) + (1.0 if _q_flag == "pass" else 0.0))
                    / _existing_gp.usage_count, 3
                )
            else:
                _sl.add(_GP(
                    org_id=org_id,
                    domain=domain or "general",
                    pattern_name=_stack_key,
                    pattern_type="tech_stack",
                    success_rate=1.0 if _q_flag == "pass" else 0.5,
                    usage_count=1,
                    avg_quality_score=_q_score,
                ))
            await _sl.commit()
            logger.info("[pipeline] Learning patterns extracted for run %s (domain=%s)", run_id, domain)
    except Exception as _le:
        logger.debug("[pipeline] Learning extraction skipped: %s", _le)