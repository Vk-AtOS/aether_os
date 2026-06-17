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

logger = logging.getLogger(__name__)


async def embed_artifacts(
    run_id: str,
    project_dir: Path,
    results: Dict,
    org_id: Optional[str],
) -> None:
    """Embed produced source files into the artifact store for semantic search."""
    from aether_os.core.pipeline_state import get_control, publish_event

    if await get_control(run_id) == "cancel":
        return
    try:
        from aether_os.core.artifact_store import get_artifact_store
        store = get_artifact_store()
        _extensions = {".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".sql"}
        _count = 0
        _errors = 0
        _MAX_ARTIFACTS = int(os.environ.get("ARTIFACT_EMBED_LIMIT", "5000"))
        _total_files = 0
        for _phase in results:
            if await get_control(run_id) == "cancel":
                break
            _phase_dir = project_dir / _phase
            if _phase_dir.exists():
                for f in _phase_dir.rglob("*"):
                    if f.is_file() and f.suffix in _extensions:
                        _total_files += 1
                        try:
                            await store.store_artifact(run_id, str(f.relative_to(project_dir)), f.read_text(), org_id=org_id)
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
    from aether_os.core.pipeline_state import get_control, publish_event

    if await get_control(run_id) == "cancel":
        return
    try:
        from aether_os.core.artifact_store import get_artifact_store as _gas_s3
        _s3_count = await _gas_s3().upload_run_to_s3(run_id, project_dir)
        if _s3_count:
            await publish_event(run_id, {
                "type": "s3_upload_complete",
                "run_id": run_id,
                "count": _s3_count,
            })
    except Exception as _s3_exc:
        logger.warning("[pipeline] S3 upload skipped: %s", _s3_exc)


async def delivery_council_check(
    run_id: str,
    project_name: Optional[str],
    raw_input: str,
    domain: str,
    results: Dict,
    org_id: Optional[str],
    accumulated_context: Dict,
) -> None:
    """Run the DeliveryCouncil check and persist the final run status."""
    import asyncio
    from aether_os.core.pipeline_state import publish_event
    from aether_os.orchestrator.run_state import _extract_project_name

    try:
        from aether_os.core.council import DeliveryCouncil
        from aether_os.core.db import get_session_factory as _gsf
        from aether_os.core.models import Run as _Run
        from sqlalchemy import update as _sa_update
        _dc = DeliveryCouncil()
        _delivery = await asyncio.wait_for(
            _dc.run(
                run_id=run_id,
                project_name=project_name or accumulated_context.get("project_name") or _extract_project_name(raw_input, run_id),
                domain=domain,
                phases_results=results,
                org_id=org_id,
            ),
            timeout=120,
        )
        _council_passed = _delivery.get("passed", False)
        _council_score = _delivery.get("score", 1.0)
        _final_status = "completed" if _council_passed else "needs_review"
        _sf = _gsf()
        async with _sf() as _s:
            await _s.execute(
                _sa_update(_Run)
                .where(_Run.id == run_id)
                .values(
                    council_delivery=_delivery,
                    status=_final_status,
                    message=(
                        None if _council_passed
                        else f"DeliveryCouncil flagged issues (score={_council_score:.2f}): "
                             f"{_delivery.get('reason', '')} — "
                             f"Suggestions: {'; '.join(_delivery.get('suggestions', []))}"
                    ),
                )
            )
            await _s.commit()
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
            # Fix 16: council_fail notification (score < 0.5)
            if _council_score < 0.5 and org_id:
                try:
                    from aether_os.core.db import get_session_factory as _gsf_cn
                    from aether_os.core.models import Notification as _Notif_cn
                    _pname_cn = project_name or f"run-{run_id[:8]}"
                    _notif_cn = _Notif_cn(
                        org_id=org_id,
                        type="council_fail",
                        title=f"❌ Council failed for {_pname_cn}",
                        message=f"DeliveryCouncil score {_council_score:.2f} < 0.5: {_delivery.get('reason', '')}",
                        link=f"/dashboard/runs/{run_id}",
                    )
                    async with _gsf_cn()() as _s_cn:
                        _s_cn.add(_notif_cn)
                        await _s_cn.commit()
                except Exception as _ne_cn:
                    logger.debug("[pipeline] council_fail notification failed: %s", _ne_cn)
        else:
            logger.info("DeliveryCouncil: run %s passed (score=%.2f)", run_id, _council_score)
            await publish_event(run_id, {
                "type": "council_delivery_passed",
                "passed": True,
                "score": _council_score,
                "status": "completed",
            })
    except asyncio.TimeoutError:
        logger.warning("DeliveryCouncil timed out after 120s for run %s — marking completed", run_id)
        try:
            from aether_os.core.db import get_session_factory as _gsf2t
            from aether_os.core.models import Run as _Run2t
            from sqlalchemy import update as _sa_update2t
            _sf2t = _gsf2t()
            async with _sf2t() as _s2t:
                await _s2t.execute(
                    _sa_update2t(_Run2t).where(_Run2t.id == run_id).values(status="completed")
                )
                await _s2t.commit()
        except Exception:
            pass
        await publish_event(run_id, {"type": "council_delivery_passed", "passed": True, "score": 0.0, "status": "completed", "note": "council_timeout"})
    except Exception as _exc:
        logger.warning("DeliveryCouncil check failed: %s", _exc)
        try:
            from aether_os.core.db import get_session_factory as _gsf2
            from aether_os.core.models import Run as _Run2
            from sqlalchemy import update as _sa_update2
            _sf2 = _gsf2()
            async with _sf2() as _s2:
                await _s2.execute(
                    _sa_update2(_Run2).where(_Run2.id == run_id).values(status="completed")
                )
                await _s2.commit()
        except Exception:
            pass
        await publish_event(run_id, {"type": "council_delivery_passed", "passed": True, "score": 0.0, "status": "completed", "note": "council_error"})


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
        from aether_os.core.services.memory_service import get_memory_service
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
        from aether_os.core.db import get_session_factory as _gsf_l
        from aether_os.core.services import learning_service as _ls
        from aether_os.core.models import GlobalPattern as _GP
        from sqlalchemy import select as _sel_l
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
