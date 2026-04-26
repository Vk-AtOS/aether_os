"""
AetherOS — 26-Phase Factory Pipeline

Each phase is a completely independent module.
All inter-phase communication goes through the MessageBus only.
The orchestrator routes messages; it never calls phase logic directly.
"""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.orchestrator.bus import get_bus, release_bus
from aether_os.orchestrator.messages import PhaseInput, PhaseMessage, PhaseResult
from aether_os.orchestrator.state_machine import (
    PipelineStateMachine, PipelineState, PHASE_TO_STATE,
)
from aether_os.orchestrator.events import (
    PIPELINE_EVENTS, ACTIVE_RUN_ID, ACTIVE_PHASE, emit,
)
from aether_os.core.projects import get_project_manager
from aether_os.core.audit.ledger import get_ledger

logger = logging.getLogger(__name__)

# Ordered 11-phase sequence (consolidated from original 26 phases)
PHASE_SEQUENCE = [
    "p01_intake_requirements",
    "p02_architecture",
    "p03_scaffolding",
    "p04_backend",
    "p05_frontend",
    "p06_review_security",
    "p07_testing",
    "p08_cicd_deployment",
    "p09_observability",
    "p10_docs_delivery",
    "p11_deployment",   # Docker build & run — delivers a live URL
]

# Legacy 26-phase map kept for reference / partial re-runs
PHASE_SEQUENCE_LEGACY = [
    "p00_intake", "p01_requirements", "p02_architecture", "p03_scaffolding",
    "p04a_backend_codegen", "p04b_uiux_design", "p04c_frontend_codegen",
    "p04d_component_library", "p04e_integration", "p05_code_review", "p06_security",
    "p07a_unit_testing", "p07b_performance_testing", "p07c_accessibility_testing",
    "p07d_e2e_testing", "p08_cicd", "p09_documentation", "p10_deployment",
    "p11a_monitoring", "p11b_error_tracking", "p11c_analytics", "p11d_alerting",
    "p12a_feature_flags", "p12b_ab_testing", "p13_app_memory", "p14_client_portal",
]

# Phase name → supervisor class path (11 consolidated phases)
PHASE_SUPERVISORS: Dict[str, str] = {
    "p01_intake_requirements": "aether_os.phases.p01_intake_requirements.IntakeRequirementsSupervisor",
    "p02_architecture":        "aether_os.phases.p02_architecture.ArchitectureSupervisor",
    "p03_scaffolding":         "aether_os.phases.p03_scaffolding.ScaffoldingSupervisor",
    "p04_backend":             "aether_os.phases.p04_backend.BackendSupervisor",
    "p05_frontend":            "aether_os.phases.p05_frontend.FrontendSupervisor",
    "p06_review_security":     "aether_os.phases.p06_review_security.ReviewSecuritySupervisor",
    "p07_testing":             "aether_os.phases.p07_testing.TestingSupervisor",
    "p08_cicd_deployment":     "aether_os.phases.p08_cicd_deployment.CICDDeploymentSupervisor",
    "p09_observability":       "aether_os.phases.p09_observability.ObservabilitySupervisor",
    "p10_docs_delivery":       "aether_os.phases.p10_docs_delivery.DocsDeliverySupervisor",
    "p11_deployment":          "aether_os.phases.p11_deployment.DeploymentSupervisor",
}


def _load_supervisor(phase_name: str):
    """Dynamically import and instantiate the supervisor for a phase."""
    class_path = PHASE_SUPERVISORS.get(phase_name)
    if not class_path:
        return None
    module_path, class_name = class_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


class FactoryPipeline:
    """
    26-phase factory pipeline.
    Routes entirely via the message bus.
    No phase imports another phase.
    """

    def __init__(self) -> None:
        self.ledger = get_ledger()
        self.pm = get_project_manager()

    async def run(self,
                  client_id: str,
                  raw_input: str,
                  domain: str = "general",
                  project_name: Optional[str] = None,
                  start_phase: Optional[str] = None,
                  run_id: Optional[str] = None) -> dict:

        run_id = run_id or str(uuid.uuid4())

        # Create project directory
        project_dir = Path.home() / ".aether_os" / "projects" / run_id
        project_dir.mkdir(parents=True, exist_ok=True)

        # Create event queue for SSE streaming
        PIPELINE_EVENTS[run_id] = asyncio.Queue(maxsize=500)

        self.ledger.save_run(run_id, f"factory: {raw_input[:60]}", "running")

        # Accumulated context passed between phases
        accumulated_context = {
            "run_id": run_id,
            "client_id": client_id,
            "raw_input": raw_input,
            "domain": domain,
            "project_name": project_name or f"project-{run_id[:8]}",
            "project_dir": str(project_dir)
        }
        
        # 10-phase consolidated pipeline
        ACTIVE_PHASES = PHASE_SEQUENCE  # All 10 consolidated phases

        phases_to_run = ACTIVE_PHASES
        if start_phase:
            all_phases = PHASE_SEQUENCE
            if start_phase in all_phases:
                phases_to_run = all_phases[all_phases.index(start_phase):]

        results = {}
        pipeline_start = time.time()
        
        for phase_name in phases_to_run:
            # Set context vars so LLM calls in this phase can emit to the queue
            run_token   = ACTIVE_RUN_ID.set(run_id)
            phase_token = ACTIVE_PHASE.set(phase_name)

            # Update state machine
            await self._update_state(run_id, phase_name, "running")
            await emit({"type": "phase_start", "phase": phase_name}, run_id=run_id)

            try:
                # Build phase input with accumulated context
                phase_input = PhaseInput(
                    run_id=run_id,
                    project_id=run_id,
                    phase=phase_name,
                    input_data=accumulated_context,
                    output_dir=str(project_dir),
                    domain=domain,
                    client_id=client_id
                )
                
                # Run phase with timeout
                phase_result = await asyncio.wait_for(
                    self._run_phase(phase_name, phase_input),
                    timeout=600)  # 10 min per phase (3b model needs time)
                
                results[phase_name] = phase_result

                # Emit file_written events for every file produced by this phase
                _phase_dir = project_dir / phase_name
                if _phase_dir.exists():
                    for _f in _phase_dir.rglob("*"):
                        if _f.is_file():
                            try:
                                _sz = _f.stat().st_size
                            except OSError:
                                _sz = 0
                            await emit({
                                "type": "file_written",
                                "phase": phase_name,
                                "path": str(_f.relative_to(project_dir)),
                                "size": _sz,
                            }, run_id=run_id)

                # Add phase output to context for next phase to use
                accumulated_context[f"{phase_name}_output"] = phase_result.get("artifacts", {})
                accumulated_context[f"{phase_name}_path"] = phase_result.get("output_path", "")

                # If p11_deployment produced a live_url, persist it to the runs table
                if phase_name == "p11_deployment":
                    _live_url = phase_result.get("metadata", {}).get("live_url")
                    if _live_url:
                        try:
                            db_path = Path.home() / ".aether_os" / "aether_os.db"
                            import aiosqlite as _aiosqlite
                            async with _aiosqlite.connect(str(db_path)) as _db:
                                # Add column if this is the first deployment
                                try:
                                    await _db.execute(
                                        "ALTER TABLE runs ADD COLUMN live_url TEXT"
                                    )
                                except Exception:
                                    pass  # Column already exists
                                await _db.execute(
                                    "UPDATE runs SET live_url=? WHERE id=?",
                                    (_live_url, run_id),
                                )
                                await _db.commit()
                            accumulated_context["live_url"] = _live_url
                        except Exception as _e:
                            logger.warning("Could not persist live_url: %s", _e)

                # Eagerly load architecture.json after p02 so all downstream
                # phases receive it via data.get("architecture_json", {}).
                if phase_name == "p02_architecture":
                    import json as _json
                    # Try the explicit output_path first, then scan the phase dir
                    _arch_candidates = []
                    _op = phase_result.get("output_path", "")
                    if _op:
                        _arch_candidates.append(Path(_op))
                    _phase_dir = project_dir / "p02_architecture"
                    _arch_candidates.append(_phase_dir / "architecture.json")
                    for _cand in _arch_candidates:
                        if _cand.exists():
                            try:
                                accumulated_context["architecture_json"] = _json.loads(
                                    _cand.read_text()
                                )
                                accumulated_context["p02_architecture_path"] = str(_cand)
                                logger.info("[pipeline] architecture_json loaded from %s", _cand)
                                break
                            except Exception as _e:
                                logger.warning("[pipeline] Failed to load architecture_json from %s: %s",
                                               _cand, _e)
                    else:
                        logger.warning("[pipeline] architecture.json not found after p02 — "
                                       "downstream phases will use their own fallbacks")
                
                # Update state
                p_status = "passed" if (phase_result.get("status") == "passed") else "completed"
                await self._update_state(run_id, phase_name, p_status)
                await emit({
                    "type": "phase_complete",
                    "phase": phase_name,
                    "status": p_status,
                    "duration": phase_result.get("duration_s"),
                }, run_id=run_id)

            except asyncio.TimeoutError:
                logger.warning(f"{phase_name} timed out, continuing")
                await self._update_state(run_id, phase_name, "timeout")
                results[phase_name] = {"status": "timeout", "output_path": ""}
                await emit({"type": "phase_complete", "phase": phase_name, "status": "timeout"}, run_id=run_id)

            except Exception as e:
                logger.error(f"{phase_name} failed: {e}")
                await self._update_state(run_id, phase_name, "failed")
                results[phase_name] = {"status": "failed", "error": str(e), "output_path": ""}
                await emit({"type": "phase_complete", "phase": phase_name, "status": "failed",
                            "error": str(e)}, run_id=run_id)
                # Continue to next phase even if this one failed

            finally:
                # Reset context vars after each phase
                ACTIVE_RUN_ID.reset(run_token)
                ACTIVE_PHASE.reset(phase_token)

            # ── Control signal check after each phase ──────────────────────
            control = PIPELINE_CONTROL.get(run_id)
            if control == "cancel":
                logger.info("Pipeline %s cancelled after phase %s", run_id, phase_name)
                self.ledger.update_run_status(run_id, "cancelled")
                _q2 = PIPELINE_EVENTS.get(run_id)
                if _q2:
                    try:
                        _q2.put_nowait({"type": "pipeline_complete", "status": "cancelled", "ts": time.time()})
                    except Exception:
                        pass
                return {
                    "run_id": run_id, "status": "cancelled",
                    "phases": results, "output_dir": str(project_dir),
                }
            if control == "pause":
                logger.info("Pipeline %s paused after phase %s", run_id, phase_name)
                self.ledger.update_run_status(run_id, "paused")
                while PIPELINE_CONTROL.get(run_id) == "pause":
                    await asyncio.sleep(2)
                if PIPELINE_CONTROL.get(run_id) == "cancel":
                    self.ledger.update_run_status(run_id, "cancelled")
                    return {
                        "run_id": run_id, "status": "cancelled",
                        "phases": results, "output_dir": str(project_dir),
                    }
                self.ledger.update_run_status(run_id, "running")

        # Mark run as complete
        await self._update_state(run_id, "pipeline", "complete")
        self.ledger.update_run_status(run_id, "completed")

        duration = time.time() - pipeline_start

        # Emit pipeline_complete so SSE clients know to close the stream
        _q = PIPELINE_EVENTS.get(run_id)
        if _q:
            try:
                await _q.put({
                    "type": "pipeline_complete",
                    "status": "completed",
                    "duration": round(duration, 1),
                    "ts": time.time(),
                })
            except Exception:
                pass
        # Schedule queue cleanup after 5 minutes
        async def _cleanup():
            await asyncio.sleep(300)
            PIPELINE_EVENTS.pop(run_id, None)
        asyncio.create_task(_cleanup())

        return {
            "run_id": run_id,
            "project_id": run_id,  # In this refactored version, run_id is used for project_dir
            "status": "complete",
            "phases": results,
            "output_dir": str(project_dir),
            "duration_seconds": round(duration, 2),
            "phase_count": len(phases_to_run)
        }

    async def _run_phase(self, phase_name: str, phase_input: PhaseInput) -> dict:
        """Execute a single phase via its supervisor."""
        supervisor = _load_supervisor(phase_name)
        if not supervisor:
             # Default success for unmapped phases to keep pipeline moving in tests
             return {"status": "completed", "output_path": "", "artifacts": {}, "metadata": {}}

        start_t = time.time()
        try:
            logger.info("[pipeline] %s starting (project_id=%s)", phase_name, phase_input.project_id)
            task_result = await supervisor.run(phase_input)
            dur = round(time.time() - start_t, 2)
            logger.info("[pipeline] %s done in %.1fs success=%s", phase_name, dur, task_result.success)
            return {
                "phase": phase_name,
                "status": "passed" if task_result.success else "failed",
                "output_path": task_result.output_path,
                "confidence": task_result.confidence,
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
            return {"status": "failed", "error": str(e), "output_path": "", "guess_dir": guess_dir}

    async def _update_state(self, run_id: str, phase: str, status: str):
        """Persist phase status to SQLite for dashboard visibility."""
        try:
            db_path = Path.home() / ".aether_os" / "aether_os.db"
            import aiosqlite
            async with aiosqlite.connect(str(db_path)) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS phase_completions (
                        run_id TEXT,
                        phase_name TEXT,
                        status TEXT,
                        updated_at REAL,
                        PRIMARY KEY (run_id, phase_name)
                    )
                """)
                await db.execute("""
                    INSERT OR REPLACE INTO phase_completions
                    (run_id, phase_name, status, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (run_id, phase, status, time.time()))
                await db.commit()
        except Exception as e:
            logger.warning(f"State update failed: {e}")
            # Don't crash pipeline on DB failure

    async def run_change_request(
        self,
        project_id: str,
        client_id: str,
        change_description: str,
        affected_areas: List[str],
    ) -> Dict[str, Any]:
        """Trigger a partial re-run for a change request."""
        # Simple implementation for now
        return await self.run(
            client_id=client_id,
            raw_input=change_description,
            project_name=f"cr-{project_id[:8]}"
        )


# Pipeline control signals — keyed by run_id: "pause" | "cancel" | None
# Set by API endpoints; checked after each phase in the loop.
PIPELINE_CONTROL: Dict[str, Optional[str]] = {}


_factory: Optional[FactoryPipeline] = None


def get_factory() -> FactoryPipeline:
    global _factory
    if _factory is None:
        _factory = FactoryPipeline()
    return _factory
