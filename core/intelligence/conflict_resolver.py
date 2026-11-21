"""Conflict Resolver — detects and resolves contradictions in requirements or design."""
from __future__ import annotations
import hashlib
import logging
from typing import Any, Dict, Optional

from aether_os.core.audit.ledger import get_ledger

logger = logging.getLogger(__name__)

RESOLVED_ACTION = "conflict.resolved"

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

    @staticmethod
    def conflict_key(conflict_id: str, description: str = "") -> str:
        """Stable key for a conflict. Detection ids ("C1") repeat between detections, so when the
        description is known the key is derived from it."""
        if description.strip():
            return "d-" + hashlib.sha256(description.strip().lower().encode()).hexdigest()[:16]
        return conflict_id

    async def resolve(self, conflict_id: str, resolution: str, run_id: str, org_id: Optional[str] = None,
                      user_id: str = "", description: str = "") -> Dict[str, Any]:
        """Record a human-provided resolution. It is stored as an org-scoped audit event, so the conflict
        counts as resolved for everyone in the organisation, and records who resolved it."""
        key = self.conflict_key(conflict_id, description)
        if org_id:
            await get_ledger().async_log_audit_event(
                org_id=org_id, user_id=user_id or "-", action=RESOLVED_ACTION,
                resource_type="conflict", resource_id=key,
                metadata={"conflict_id": conflict_id, "resolution": resolution[:2000], "run_id": run_id,
                          "description": description.strip()[:500]})
        try:
            get_ledger().log_event(
                run_id, "conflict_resolver", "conflict_resolved",
                {"conflict_id": conflict_id, "resolution": resolution},
                org_id=org_id,
            )
        except Exception as exc:
            logger.warning("ConflictResolver.resolve audit log failed: %s", exc)
        return {"resolved": True, "conflict_id": conflict_id, "key": key,
                "resolution": resolution, "resolved_by": user_id}

    async def list_resolved(self, org_id: str) -> Dict[str, Any]:
        """Conflicts any member of the org has resolved: key -> {resolution, resolved_by, resolved_at}."""
        res = await get_ledger().async_get_audit_logs(org_id, page=1, limit=500, action=RESOLVED_ACTION)
        out: Dict[str, Any] = {}
        for row in reversed(res.get("logs", [])):  # oldest first, so the latest resolution wins
            out[row["resource_id"]] = {
                "resolution": (row.get("metadata") or {}).get("resolution", ""),
                "description": (row.get("metadata") or {}).get("description", ""),
                "resolved_by": row.get("user_id", ""),
                "resolved_at": row.get("created_at"),
            }
        return {"resolved": out}


def get_conflict_resolver() -> ConflictResolver:
    global _instance
    if _instance is None:
        _instance = ConflictResolver()
    return _instance
