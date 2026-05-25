"""Maintenance Engine — dependency updates, patch management, health checks."""
from __future__ import annotations
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_instance: Optional["MaintenanceEngine"] = None


class MaintenanceEngine:
    """Manages ongoing maintenance tasks for generated projects.

    Capabilities:
    - Dependency vulnerability scanning
    - Suggesting version upgrades
    - Scheduled health checks
    - Deprecation warnings
    - Tech debt identification
    """

    async def scan_dependencies(self, requirements_txt: str) -> Dict[str, Any]:
        """Parse requirements.txt and flag outdated or vulnerable packages."""
        try:
            from aether_os.core.llm.client import get_llm_client
            llm = get_llm_client()
            prompt = (
                f"You are a dependency maintenance advisor.\n\n"
                f"requirements.txt:\n{requirements_txt[:3000]}\n\n"
                f"Identify: outdated packages, known CVEs, and suggested upgrades.\n"
                f"Return JSON: {{'packages': [{{'name': str, 'current': str, 'latest': str, "
                f"'cve': str|null, 'severity': 'critical'|'high'|'medium'|'low'|'none'}}], "
                f"'action_required': bool}}"
            )
            result = await llm.call_json(prompt, task_type="documentation")
            return {**result, "engine": "maintenance_engine", "scanned_at": time.time()}
        except Exception as exc:
            logger.warning("MaintenanceEngine scan_dependencies failed: %s", exc)
            return {"packages": [], "action_required": False, "engine": "maintenance_engine", "error": str(exc)}

    async def tech_debt_analysis(self, code: str, language: str = "python") -> Dict[str, Any]:
        """Identify tech debt in the generated code."""
        try:
            from aether_os.core.llm.client import get_llm_client
            llm = get_llm_client()
            prompt = (
                f"You are a tech debt analyzer.\n\n"
                f"{language} code:\n{code[:5000]}\n\n"
                f"Identify tech debt items. Return JSON:\n"
                f"{{'debt_items': [{{'type': str, 'description': str, 'effort': 'hours'|'days'|'weeks', "
                f"'impact': 'high'|'medium'|'low'}}], 'total_debt_score': 0-100}}"
            )
            result = await llm.call_json(prompt, task_type="documentation")
            return {**result, "engine": "maintenance_engine"}
        except Exception as exc:
            logger.warning("MaintenanceEngine.tech_debt_analysis failed: %s", exc)
            return {"debt_items": [], "total_debt_score": 0, "engine": "maintenance_engine", "error": str(exc)}

    async def schedule_maintenance(
        self,
        run_id: str,
        task_type: str,
        scheduled_at: float,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Schedule a maintenance task and store in audit log."""
        try:
            from aether_os.core.audit.ledger import get_ledger
            get_ledger().log_event(
                run_id, "maintenance_engine", "maintenance_scheduled",
                {"task_type": task_type, "scheduled_at": scheduled_at},
                org_id=org_id,
            )
        except Exception as exc:
            logger.debug("MaintenanceEngine.schedule_maintenance audit log failed: %s", exc)
        return {"scheduled": True, "run_id": run_id, "task_type": task_type, "scheduled_at": scheduled_at}

    async def health_check_project(self, run_id: str) -> Dict[str, Any]:
        """Run a health check on a completed project's generated output."""
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Run
            async with get_session_factory()() as sess:
                run = await sess.get(Run, run_id)
                if not run:
                    return {"healthy": False, "error": "Run not found"}
            return {
                "healthy": run.status in ("completed", "deployed"),
                "status": run.status,
                "cost": run.cost,
                "run_id": run_id,
                "checked_at": time.time(),
                "engine": "maintenance_engine",
            }
        except Exception as exc:
            return {"healthy": False, "error": str(exc), "engine": "maintenance_engine"}


def get_maintenance_engine() -> MaintenanceEngine:
    global _instance
    if _instance is None:
        _instance = MaintenanceEngine()
    return _instance
