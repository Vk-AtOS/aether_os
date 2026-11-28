"""
AetherOS — 12-Stage Factory Pipeline (orchestrator/phase_sequence.py is the list)

Each phase is a completely independent module.
All inter-phase communication goes through the MessageBus only.
The orchestrator routes messages; it never calls phase logic directly.

Phase registry data lives in orchestrator/phase_sequence.py.
Run-state helpers live in orchestrator/run_state.py.

KAN-57: the run itself is steps on a PipelineRun (pipeline_run.py, pipeline_steps.py,
pipeline_phase_post.py, pipeline_questionnaire.py; design in docs/design/pipeline_run.md).
This module keeps FactoryPipeline and re-exports every name it ever had: the moved steps
read their collaborators from here at call time (tests patch them here), so the unused-looking
imports below are load-bearing.
"""
# ruff: noqa: F401
from __future__ import annotations
import secrets
import json as _json
from sqlalchemy import update as _sa_update
from sqlalchemy import select as _sel, update as _upd
from aether_os.integrations.aether2_bridge import ExternalMonitorBridge
from aether_os.core.services.learning_service import get_user_context
from aether_os.core.questionnaire.stage_questions import get_stage_questions
from aether_os.core.models import Run as _Run_canc
from aether_os.core.models import Run as _Run
from aether_os.core.models import QuestionnaireSession, Run
from aether_os.core.decisions.decision_engine import get_decision_engine
from aether_os.core.models import Organisation
from aether_os.core.llm.client import init_org_llm_context
from aether_os.core.identity.zero_trust import issue_ticket as _zt_issue
from aether_os.core.db_utils import create_run as _create_run
from aether_os.core.db import get_session_factory as _gsf_q
from aether_os.core.db import get_session_factory as _gsf_canc
from aether_os.core.db import get_session_factory as _gsf
from aether_os.core.db import get_session_factory
import asyncio
import sys
from aether_os.orchestrator.pipeline_run import PipelineRun, prepare as prepare_run
from aether_os.orchestrator.pipeline_steps import execute as execute_run
from aether_os.orchestrator.pipeline_questionnaire import _pause_for_questionnaire
import logging
import time
import uuid
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.orchestrator.context_schema import assert_context, validate_context_after_stage
from aether_os.orchestrator.messages import PhaseInput
from aether_os.orchestrator.events import (
    ACTIVE_RUN_ID, ACTIVE_PHASE, ACTIVE_ORG_ID, emit, publish_event,
)
from aether_os.core.pipeline_state import get_control, set_control, clear_run
from aether_os.core.security.redact import redact_secrets
from aether_os.core.projects import get_project_manager
from aether_os.core.audit.ledger import get_ledger
from aether_os.core.project_memory import (
    init_memory as _pm_init,
    update_memory as _pm_update,
    add_changelog_entry as _pm_changelog,
)
from aether_os.orchestrator.phase_sequence import (
    CRITICAL_PHASES,
    PHASE_SEQUENCE,
    PHASE_SUPERVISORS,  # noqa: F401  re-exported: tests and tooling import it from here
    _load_supervisor,
)
from aether_os.orchestrator.run_state import (
    _extract_project_name,
    _get_pipeline_semaphore,
    update_phase_state,
    save_checkpoint,
)
from aether_os.orchestrator.artifact_collector import (
    embed_artifacts,
    upload_to_s3,
    delivery_council_check,
    extract_learning,
    store_run_memory,
)
from aether_os.orchestrator.phase_dag import get_execution_waves
from aether_os.orchestrator.parallel_runner import run_phases_in_wave
from aether_os.orchestrator.phase_selector import (
    select_phases,
    resolve_change_request_phase,
    restore_from_checkpoint,
)
from aether_os.orchestrator.phase_hooks import run_phase_hooks
from aether_os.core.run_limits import pipeline_timeout_seconds
from aether_os.orchestrator.stage_gate import (
    apply_stage_toggles,
    gate_block_reason,
    load_disabled_stages,
    recorded_status,
    record_run_timeout,
    summarize_stage_outcomes,
    timeout_reason,
)
from aether_os.orchestrator.phase_hooks_helpers import hook_persist_live_url
from aether_os.orchestrator import messages as _messages_module
from aether_os.orchestrator.bus import release_bus
from aether_os.orchestrator.pipeline_completion import (
    persist_finished_at,
    schedule_completion_tasks,
)

logger = logging.getLogger(__name__)

def _slots_in_use(sem: asyncio.Semaphore, limit: int) -> int:
    """Slots held right now. (The old log line computed `value ^ limit - value`: ^ binds looser
    than -, so it printed an XOR, not the count.)"""
    return max(0, limit - sem._value)


class FactoryPipeline:
    """
    12-stage factory pipeline (s01_intake .. s12_specialist; each stage runs one or more phase agents).
    Routes entirely via the message bus.
    No phase imports another phase.
    """

    def __init__(self) -> None:
        self.ledger = get_ledger()
        self.pm = get_project_manager()
        self._background_tasks = set()

    async def run(self,
                  client_id: str,
                  raw_input: str,
                  domain: str = "general",
                  project_name: Optional[str] = None,
                  start_phase: Optional[str] = None,
                  run_id: Optional[str] = None,
                  org_id: Optional[str] = None,
                  org_slug: Optional[str] = None,
                  plan: Optional[str] = None,
                  is_change_request: bool = False,
                  memory_context: Optional[str] = None,
                  council_preflight: Optional[Dict[str, Any]] = None,
                  github_url: Optional[str] = None,
                  designer_spec: Optional[Dict[str, Any]] = None,
                  tech_preferences: Optional[Dict[str, Any]] = None,
                  model_preference: Optional[str] = None,
                  priority: Optional[str] = None,
                  codebase_mode: Optional[str] = None,
                  existing_schema: Optional[Dict[str, Any]] = None,
                  # Q1 / Q4: enrichment fields
                  user_personas: Optional[List[Dict[str, Any]]] = None,
                  has_customer_portal: Optional[bool] = None,
                  has_landing_page: bool = False,
                  app_brand: Optional[Dict[str, Any]] = None,
                  realtime_features: Optional[List[str]] = None,
                  seed_vocabulary: Optional[Dict[str, Any]] = None,
                  multi_tenancy: Optional[bool] = None,
                  mode: str = "autonomous",
                  intake_answers: Optional[Dict[str, Any]] = None,
                  respondent_email: Optional[str] = None,
                  agency_name: Optional[str] = None,
                  agency_logo_url: Optional[str] = None) -> dict:

        timeout = pipeline_timeout_seconds()
        sem = _get_pipeline_semaphore()
        _limit = int(os.environ.get("PIPELINE_MAX_CONCURRENT", "2"))
        logger.info("Pipeline %s waiting for concurrency slot (%d/%d in use)", run_id, _slots_in_use(sem, _limit), _limit)
        async with sem:
            logger.info("Pipeline %s acquired concurrency slot", run_id)
            # Store sem on the instance so _pause_for_questionnaire can release it
            # during guided-mode waits without holding the concurrency slot for up to 7 days.
            self._pipeline_sem = sem
            try:
                return await asyncio.wait_for(self._execute_pipeline(
                    client_id, raw_input, domain, project_name, start_phase,
                    run_id, org_id, org_slug, plan, is_change_request, memory_context,
                    council_preflight, github_url, designer_spec or {},
                    tech_preferences, model_preference, priority, codebase_mode, existing_schema,
                    user_personas, has_customer_portal, has_landing_page,
                    app_brand, realtime_features, seed_vocabulary, multi_tenancy,
                    mode=mode, intake_answers=intake_answers,
                    respondent_email=respondent_email, agency_name=agency_name,
                    agency_logo_url=agency_logo_url,
                ), timeout=timeout)
            except asyncio.TimeoutError:
                logger.error("Pipeline %s timed out after %s minutes", run_id, timeout / 60)
                reason = await record_run_timeout(self.ledger, run_id, timeout) if run_id else None
                if run_id:
                    await publish_event(run_id, {"type": "pipeline_complete", "status": "timeout", "error": reason, "ts": time.time()})
                return {"run_id": run_id, "status": "timeout", "error": reason}
            finally:
                # However the run ended, no approval may stay 'pending' forever (KAN-248).
                if run_id:
                    await get_decision_engine().expire_pending(run_id, "expired")

    async def _execute_pipeline(self,
                  client_id: str,
                  raw_input: str,
                  domain: str = "general",
                  project_name: Optional[str] = None,
                  start_phase: Optional[str] = None,
                  run_id: Optional[str] = None,
                  org_id: Optional[str] = None,
                  org_slug: Optional[str] = None,
                  plan: Optional[str] = None,
                  is_change_request: bool = False,
                  memory_context: Optional[str] = None,
                  council_preflight: Optional[Dict[str, Any]] = None,
                  github_url: Optional[str] = None,
                  designer_spec: Optional[Dict[str, Any]] = None,
                  tech_preferences: Optional[Dict[str, Any]] = None,
                  model_preference: Optional[str] = None,
                  priority: Optional[str] = None,
                  codebase_mode: Optional[str] = None,
                  existing_schema: Optional[Dict[str, Any]] = None,
                  # Q1 / Q4: enrichment fields
                  user_personas: Optional[List[Dict[str, Any]]] = None,
                  has_customer_portal: Optional[bool] = None,
                  has_landing_page: bool = False,
                  app_brand: Optional[Dict[str, Any]] = None,
                  realtime_features: Optional[List[str]] = None,
                  seed_vocabulary: Optional[Dict[str, Any]] = None,
                  multi_tenancy: Optional[bool] = None,
                  mode: str = "autonomous",
                  intake_answers: Optional[Dict[str, Any]] = None,
                  respondent_email: Optional[str] = None,
                  agency_name: Optional[str] = None,
                  agency_logo_url: Optional[str] = None) -> dict:
        """One run, as steps on a PipelineRun (docs/design/pipeline_run.md)."""
        run = PipelineRun(
            fp=sys.modules[__name__], pipeline=self, client_id=client_id, raw_input=raw_input,
            domain=domain, project_name=project_name, start_phase=start_phase,
            run_id=run_id or "", org_id=org_id, org_slug=org_slug, plan=plan,
            is_change_request=is_change_request, memory_context=memory_context,
            council_preflight=council_preflight, github_url=github_url,
            designer_spec=designer_spec, tech_preferences=tech_preferences,
            model_preference=model_preference, priority=priority,
            codebase_mode=codebase_mode, existing_schema=existing_schema,
            user_personas=user_personas, has_customer_portal=has_customer_portal,
            has_landing_page=has_landing_page, app_brand=app_brand,
            realtime_features=realtime_features, seed_vocabulary=seed_vocabulary,
            multi_tenancy=multi_tenancy, mode=mode, intake_answers=intake_answers,
            respondent_email=respondent_email, agency_name=agency_name,
            agency_logo_url=agency_logo_url,
        )
        ended = await prepare_run(run)
        if ended is not None:
            return ended
        return await execute_run(run)

    async def _run_phase(self, phase_name: str, phase_input: PhaseInput) -> dict:
        """Execute a single phase via its supervisor."""
        supervisor = _load_supervisor(phase_name)
        if not supervisor:
            logger.warning(
                "[pipeline] No supervisor mapped for phase %r — skipping. "
                "Check PHASE_SUPERVISORS in factory_pipeline.py.",
                phase_name,
            )
            return {"status": "skipped", "output_path": "", "artifacts": {}, "metadata": {},
                    "warning": f"No supervisor mapped for phase {phase_name!r}"}

        # Issue a zero-trust ticket that authorises this phase to act on its
        # designated output directory within the current run.  The ticket is
        # embedded in phase_input so the supervisor can verify it before
        # executing privileged operations.
        try:

            _zt_ticket = _zt_issue(
                project_path=phase_input.run_id,
                resource_path=phase_input.output_dir,
                action=phase_name,
            )
            phase_input = phase_input.model_copy(
                update={"input_data": {**phase_input.input_data, "_zt_ticket": _zt_ticket}}
            )
        except Exception as _zt_exc:
            logger.warning("[pipeline] Zero-trust ticket issuance failed for %s (non-fatal): %s",
                           phase_name, _zt_exc)

        start_t = time.time()
        try:
            logger.info("[pipeline] %s starting (project_id=%s)", phase_name, phase_input.project_id)
            task_result = await supervisor.run(phase_input)
            dur = round(time.time() - start_t, 2)
            logger.info("[pipeline] %s done in %.1fs success=%s", phase_name, dur, task_result.success)
            if task_result.escalated:
                phase_status = "escalated"
            elif task_result.success:
                phase_status = "passed"
            else:
                phase_status = "failed"
            return {
                "phase": phase_name,
                "status": phase_status,
                "output_path": task_result.output_path,
                "confidence": task_result.confidence,
                "confidence_reason": task_result.confidence_reason,
                "issues": task_result.issues,
                "metadata": task_result.metadata,
                "artifacts": task_result.metadata.get("artifacts", {}),
                "duration_s": dur,
            }
        except asyncio.CancelledError:
            # CancelledError is BaseException — re-raise so wait_for converts to TimeoutError
            logger.warning("[pipeline] %s cancelled (likely parent timeout)", phase_name)
            raise
        except BaseException as e:
            dur = round(time.time() - start_t, 2)
            logger.error("[pipeline] %s crashed after %.1fs: %s: %s",
                         phase_name, dur, type(e).__name__, e)
            # Determine a best-guess output_path so downstream phases aren't starved
            guess_dir = str(
                Path.home() / ".aether_os" / "projects"
                / phase_input.run_id / phase_name
            )
            return {"status": "failed", "error": redact_secrets(f"{type(e).__name__}: {e}"),
                    "output_path": "", "guess_dir": guess_dir}

    async def _abort_run(self, run_id: str, message: str,
                         failed_stage: Optional[str] = None) -> dict:
        """End the run as failed: store the redacted reason, tell the live view, stop.

        Every abort goes through here so the reason on Run.message, in the event
        stream and in the returned result is the same redacted text.
        """
        reason = redact_secrets(message)
        await self.ledger.async_update_run_status(run_id, "failed", message=reason)
        await persist_finished_at(run_id)
        try:
            await publish_event(run_id, {"type": "pipeline_complete", "status": "failed",
                                         "error": reason, "failed_stage": failed_stage,
                                         "ts": time.time()})
            release_bus(run_id)
        except Exception as exc:
            # The run is already stored as failed; a lost event must not un-stop it.
            logger.warning("[pipeline] could not publish the failure of run %s: %s", run_id, exc)
        return {"run_id": run_id, "status": "failed", "error": reason,
                "failed_stage": failed_stage}

    async def _update_state(self, run_id: str, phase: str, status: str):
        """Persist phase status via ORM — delegates to run_state.update_phase_state."""
        await update_phase_state(run_id, phase, status)

    async def run_change_request(
        self,
        project_id: str,
        client_id: str,
        change_description: str,
        affected_areas: List[str],
        org_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Trigger a partial re-run from the first affected phase.

        Loads the original run's accumulated context so downstream phases
        receive prior phase outputs (architecture, scaffolding, etc.)
        and only the affected subset is re-executed.
        """
        # Resolve affected area names to the earliest phase that must re-run.
        first_phase = resolve_change_request_phase(
            affected_areas=affected_areas,
            phase_sequence=PHASE_SEQUENCE,
            default_phase="s03_backend",
        )

        # Load original run's context so downstream phases have prior outputs.
        # Carry plan, domain, org_slug from the original run so change-request
        # runs don't silently default to "trial"/"general" and bypass quota checks.
        original_context: Dict[str, Any] = {}
        _orig_plan: Optional[str] = None
        _orig_domain: str = "general"
        _orig_org_slug: Optional[str] = None
        try:
            original_dir = Path.home() / ".aether_os" / "projects" / project_id
            if original_dir.exists():

                mem_path = original_dir / "project_memory.json"
                if mem_path.exists():
                    original_context = _json.loads(mem_path.read_text())
                # Expose original project dir so phases can read existing code
                original_context["original_project_dir"] = str(original_dir)
                original_context["base_project_id"] = project_id
                _orig_plan = original_context.get("plan")
                _orig_domain = original_context.get("domain", "general")
                _orig_org_slug = original_context.get("org_slug")
        except Exception as _e:
            logger.debug("[change_request] Could not load original context: %s", _e)

        return await self.run(
            client_id=client_id,
            raw_input=change_description,
            project_name=f"cr-{project_id[:8]}",
            start_phase=first_phase,
            is_change_request=True,
            org_id=org_id,
            org_slug=_orig_org_slug,
            plan=_orig_plan,
            domain=_orig_domain,
            run_id=run_id,
            memory_context=json.dumps(original_context) if original_context else None,
        )

# B5: Strong references to background tasks prevent GC from silently killing them.

_factory: Optional[FactoryPipeline] = None

def get_factory() -> FactoryPipeline:
    global _factory
    if _factory is None:
        _factory = FactoryPipeline()
    return _factory

