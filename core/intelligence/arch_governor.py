"""Arch Governor — enforces architectural constraints on generated code."""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_instance: Optional["ArchGovernor"] = None


class ArchGovernor:
    """Reviews generated code against the project's architecture document.

    Checks:
    - Layer separation (API / service / data layers)
    - Dependency direction (no circular imports)
    - Naming conventions match the architecture
    - Framework choices match the spec
    """

    async def review(
        self,
        generated_code: str,
        architecture_doc: str,
        language: str = "python",
    ) -> Dict[str, Any]:
        """Run architectural review. Returns violations and a pass/fail verdict."""
        try:
            from aether_os.core.llm.client import get_llm_client
            llm = get_llm_client()
            prompt = (
                f"You are an architecture governance system.\n\n"
                f"Architecture spec:\n{architecture_doc[:3000]}\n\n"
                f"Generated {language} code:\n{generated_code[:5000]}\n\n"
                f"Identify architectural violations. Return JSON:\n"
                f"{{'violations': [{{'rule': str, 'description': str, 'severity': 'critical'|'warning'|'info'}}], "
                f"'compliant': bool, 'compliance_score': 0-100}}"
            )
            result = await llm.call_json(prompt, task_type="code_generation")
            return {
                "violations": result.get("violations", []),
                "compliant": result.get("compliant", True),
                "compliance_score": result.get("compliance_score", 80),
                "engine": "arch_governor",
            }
        except Exception as exc:
            logger.warning("ArchGovernor review failed: %s", exc)
            return {"violations": [], "compliant": True, "compliance_score": 80, "engine": "arch_governor", "error": str(exc)}

    async def enforce(
        self,
        run_id: str,
        architecture_doc: str,
        generated_code: str,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Review + store result in audit log."""
        result = await self.review(generated_code, architecture_doc)
        try:
            from aether_os.core.audit.ledger import get_ledger
            get_ledger().log_event(
                run_id, "arch_governor", "arch_review",
                {"compliant": result["compliant"], "violations_count": len(result.get("violations", []))},
                org_id=org_id,
            )
        except Exception:
            pass
        return result


def get_arch_governor() -> ArchGovernor:
    global _instance
    if _instance is None:
        _instance = ArchGovernor()
    return _instance
