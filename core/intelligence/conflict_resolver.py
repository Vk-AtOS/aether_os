"""Conflict Resolver — detects and resolves contradictions in requirements or design."""
from __future__ import annotations
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_instance: Optional["ConflictResolver"] = None


class ConflictResolver:
    """Identifies conflicting requirements or architectural decisions and proposes resolutions.

    Common conflicts:
    - Performance vs. consistency (CAP theorem choices)
    - Security vs. usability
    - Cost vs. reliability
    - Scalability vs. simplicity
    """

    async def detect(
        self,
        requirements: str,
        constraints: str = "",
        architecture_doc: str = "",
    ) -> Dict[str, Any]:
        """Detect conflicts in the given requirements/constraints."""
        try:
            from aether_os.core.llm.client import get_llm_client
            llm = get_llm_client()
            context = f"Requirements:\n{requirements[:2000]}"
            if constraints:
                context += f"\n\nConstraints:\n{constraints[:1000]}"
            if architecture_doc:
                context += f"\n\nArchitecture:\n{architecture_doc[:1000]}"
            prompt = (
                f"You are a requirements conflict detector.\n\n{context}\n\n"
                f"Identify any conflicts, contradictions, or ambiguities.\n"
                f"Return JSON: {{'conflicts': [{{'id': str, 'description': str, 'items_involved': [str], "
                f"'severity': 'blocking'|'major'|'minor', 'resolution': str}}], 'conflict_free': bool}}"
            )
            result = await llm.call_json(prompt, task_type="code_generation")
            return {
                "conflicts": result.get("conflicts", []),
                "conflict_free": result.get("conflict_free", True),
                "engine": "conflict_resolver",
            }
        except Exception as e:
            logger.warning("conflict_resolver LLM unavailable, using static fallback: %s", e)
            return {
                "conflicts": [],
                "conflict_free": True,
                "engine": "static_fallback",
                "note": "LLM unavailable — static fallback assumes no conflicts",
            }

    async def resolve(self, conflict_id: str, resolution: str, run_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
        """Record a human-provided resolution for a conflict."""
        try:
            from aether_os.core.audit.ledger import get_ledger
            get_ledger().log_event(
                run_id, "conflict_resolver", "conflict_resolved",
                {"conflict_id": conflict_id, "resolution": resolution},
                org_id=org_id,
            )
        except Exception as exc:
            logger.warning("ConflictResolver.resolve audit log failed: %s", exc)
        return {"resolved": True, "conflict_id": conflict_id, "resolution": resolution}


def get_conflict_resolver() -> ConflictResolver:
    global _instance
    if _instance is None:
        _instance = ConflictResolver()
    return _instance
