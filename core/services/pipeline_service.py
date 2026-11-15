"""
AetherOS — PipelineService

The service layer between FastAPI route handlers and the database/pipeline.
Route handlers call PipelineService methods — they do NOT touch the DB directly.

This is the root fix for the "business logic baked into HTTP handlers" problem.
"""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Strong references prevent GC from silently killing background tasks
_background_tasks: set = set()


class PipelineService:
    """
    Orchestrates all factory pipeline operations.
    Single responsibility: bridge between API layer and pipeline/DB layer.
    """

    async def start_run(
        self,
        *,
        org_id: str,
        org_slug: str,
        plan: str,
        raw_input: str,
        project_name: Optional[str] = None,
        domain: str = "general",
        client_id: Optional[str] = None,
        is_change_request: bool = False,
        memory_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start a new pipeline run. Returns {run_id, status}."""
        from aether_os.core.db_utils import create_run
        from aether_os.core.rate_limiter import get_rate_limiter
        from aether_os.orchestrator.factory_pipeline import get_factory
        from aether_os.core.policy.engine import get_policy_engine

        rl = get_rate_limiter()
        if not await rl.check_concurrent_runs(org_id):
            raise ValueError("Organisation has reached the concurrent run limit.")
        if not await rl.check_hourly_starts(org_id):
            raise ValueError("Organisation has exceeded the hourly run limit.")

        # Plan sanity check. The full decision (role, quotas, trial allowance) is made
        # by the caller through gateway.policy_guard.admit_run_start before this runs.
        ok, msg = get_policy_engine().check_pipeline_start(org_id=org_id, plan=plan)
        if not ok:
            raise ValueError(msg)

        run_id = str(uuid.uuid4())
        pname = project_name or raw_input[:60].replace("\n", " ")

        await create_run(
            run_id=run_id,
            command=f"factory: {pname}",
            org_id=org_id,
            project_name=pname,
            domain=domain,
            client_id=client_id,
            raw_input=raw_input,
        )
        await rl.record_run_start(org_id)

        # Inject cross-run memory context if memory system is available
        mem_ctx = memory_context
        if not mem_ctx:
            try:
                from aether_os.core.services.memory_service import MemoryService
                ms = MemoryService()
                mem_ctx = await ms.get_context_for_run(org_id=org_id, raw_input=raw_input)
            except Exception as exc:
                logger.debug("Memory service unavailable: %s", exc)

        factory = get_factory()
        _t = asyncio.create_task(
            factory.run(
                run_id=run_id,
                raw_input=raw_input,
                org_id=org_id,
                org_slug=org_slug,
                plan=plan,
                domain=domain,
                client_id=client_id or "client-001",
                is_change_request=is_change_request,
                memory_context=mem_ctx or "",
            )
        )
        _background_tasks.add(_t)
        _t.add_done_callback(_background_tasks.discard)

        return {"run_id": run_id, "status": "started"}

    async def get_run(self, run_id: str, org_id: str) -> Dict[str, Any]:
        from aether_os.core.db_utils import get_run_detail
        detail = await get_run_detail(run_id, org_id=org_id)
        if not detail:
            raise LookupError(f"Run {run_id} not found")
        return detail

    async def list_runs(self, org_id: str, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        from aether_os.core.db_utils import get_run_list
        return await get_run_list(org_id=org_id, limit=limit, offset=offset)

    async def pause_run(self, run_id: str, org_id: str) -> None:
        from aether_os.core.db_utils import update_run_status
        from aether_os.core.pipeline_state import set_control
        await set_control(run_id, "pause")
        await update_run_status(run_id, "paused", org_id=org_id)
        await self._log_audit(org_id, run_id, "run.paused")

    async def resume_run(self, run_id: str, org_id: str) -> None:
        from aether_os.core.db_utils import update_run_status
        from aether_os.core.pipeline_state import set_control
        await set_control(run_id, "run")
        await update_run_status(run_id, "running", org_id=org_id)
        await self._log_audit(org_id, run_id, "run.resumed")

    async def cancel_run(self, run_id: str, org_id: str) -> None:
        from aether_os.core.db_utils import update_run_status
        from aether_os.core.pipeline_state import set_control
        await set_control(run_id, "cancel")
        await update_run_status(run_id, "cancelled", org_id=org_id)
        await self._log_audit(org_id, run_id, "run.cancelled")

    async def set_priority(self, run_id: str, org_id: str, priority: str) -> None:
        from aether_os.core.db_utils import set_run_priority
        ok = await set_run_priority(run_id, org_id, priority)
        if not ok:
            raise LookupError(f"Run {run_id} not found or not owned by org {org_id}")

    async def _log_audit(self, org_id: str, resource_id: str, action: str) -> None:
        try:
            from aether_os.core.audit.ledger import get_ledger
            await get_ledger().async_log_audit_event(
                org_id=org_id, user_id="system", action=action,
                resource_type="run", resource_id=resource_id,
                metadata={}, ip_address="internal",
            )
        except Exception as exc:
            logger.warning("PipelineService._log_audit: audit event %s failed (non-blocking): %s", action, exc)


_pipeline_service: Optional[PipelineService] = None


def get_pipeline_service() -> PipelineService:
    global _pipeline_service
    if _pipeline_service is None:
        _pipeline_service = PipelineService()
    return _pipeline_service
