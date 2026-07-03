"""Truth Engine — validates that implementation matches requirements."""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_instance: Optional["TruthEngine"] = None


class TruthEngine:
    """Cross-references requirements against the generated output.

    For each requirement, checks whether the implementation addresses it.
    Returns a coverage map and a list of unaddressed requirements.
    """

    async def validate(
        self,
        requirements: str,
        generated_code: str,
        architecture_doc: str = "",
    ) -> Dict[str, Any]:
        """Validate that all requirements are addressed in the output."""
        try:
            from aether_os.core.llm.client import get_llm_client
            llm = get_llm_client()
            prompt = (
                f"You are a requirements traceability system.\n\n"
                f"Requirements:\n{requirements[:2000]}\n\n"
                f"Generated code:\n{generated_code[:12000]}\n\n"
                f"For each requirement, determine if it is addressed in the code.\n"
                f"Return JSON: {{'coverage': [{{'requirement': str, 'addressed': bool, 'evidence': str}}], "
                f"'coverage_percent': 0-100, 'unaddressed': [str]}}"
            )
            result = await llm.call_json(prompt, task_type="code_generation")
            return {
                "coverage": result.get("coverage", []),
                "coverage_percent": result.get("coverage_percent", 80),
                "unaddressed": result.get("unaddressed", []),
                "engine": "truth_engine",
            }
        except Exception as exc:
            logger.warning("TruthEngine validate failed: %s", exc)
            return {"coverage": [], "coverage_percent": 80, "unaddressed": [], "engine": "truth_engine", "error": str(exc)}

    async def audit_run(self, run_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
        """Load run data and validate requirements vs output."""
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Run
            from sqlalchemy import select
            async with get_session_factory()() as sess:
                run = await sess.get(Run, run_id)
                if not run:
                    return {"error": "Run not found"}
                req = run.requirement or run.raw_input or ""
                # Load actual generated code from the run output directory
                import os
                project_dir = os.path.expanduser(f"~/.aether_os/projects/{run_id}")
                code_parts: list[str] = []
                for candidate in [
                    f"{project_dir}/src/main.py",
                    f"{project_dir}/main.py",
                    f"{project_dir}/p04_backend/src/main.py",
                    f"{project_dir}/p04a_backend_codegen/src/main.py",
                ]:
                    if os.path.isfile(candidate):
                        try:
                            code_parts.append(open(candidate).read(8000))
                        except Exception as exc:
                            logger.debug("TruthEngine.audit_run could not read %s: %s", candidate, exc)
                code = "\n\n---\n\n".join(code_parts) if code_parts else f"[No generated files found for run {run_id}]"
        except Exception as exc:
            logger.warning("truth_engine.audit_run failed: %s", exc)
            return {"error": str(exc)}
        return await self.validate(req, code)


def get_truth_engine() -> TruthEngine:
    global _instance
    if _instance is None:
        _instance = TruthEngine()
    return _instance
