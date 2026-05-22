"""
AetherOS — MemoryService

Unified memory layer wrapping all four memory systems:
  1. graph_rag       — repo graph analysis (symbol index, call graph)
  2. knowledge_graph — persistent concept/entity graph per org
  3. fingerprinter   — project fingerprinting for similarity detection
  4. matcher         — matches new project to past runs for context injection

This is how cross-run learning works:
  1. New run arrives → fingerprint the raw_input
  2. Match fingerprint against past successful runs
  3. Inject matched past outputs as memory_context into pipeline
  4. Post-run: store the new fingerprint + outputs for future matches

Session memory uses the user_preferences JSON column on the User model.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryService:
    """
    Unified interface to all memory subsystems.
    All methods are async-safe (blocking calls run in executor).
    """

    async def get_context_for_run(
        self,
        org_id: str,
        raw_input: str,
        top_k: int = 3,
    ) -> str:
        """
        Return a memory_context string to inject into the pipeline.
        Combines: fingerprint match → past winning phase outputs → JSON summary.
        """
        try:
            matches = await self._find_similar_runs(org_id=org_id, raw_input=raw_input, top_k=top_k)
            if not matches:
                return ""
            ctx_parts = []
            for match in matches[:top_k]:
                similarity = match.get("similarity", 0.0)
                if similarity < 0.4:
                    continue
                ctx_parts.append({
                    "run_id":     match["run_id"],
                    "similarity": round(similarity, 3),
                    "project":    match.get("project_name", ""),
                    "domain":     match.get("domain", ""),
                    "hint":       match.get("winning_approach", ""),
                })
            if not ctx_parts:
                return ""
            return json.dumps({"past_similar_runs": ctx_parts}, ensure_ascii=False)
        except Exception as exc:
            logger.debug("MemoryService.get_context_for_run failed: %s", exc)
            return ""

    async def store_run_outcome(
        self,
        org_id: str,
        run_id: str,
        raw_input: str,
        status: str,
        domain: str = "general",
        phase_outputs: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store fingerprint + outcome for future cross-run learning."""
        if status not in ("completed", "passed"):
            return  # Only learn from successful runs
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._sync_store_outcome,
                                        org_id, run_id, raw_input, domain, phase_outputs or {})
        except Exception as exc:
            logger.debug("MemoryService.store_run_outcome failed: %s", exc)

    def _sync_store_outcome(
        self,
        org_id: str,
        run_id: str,
        raw_input: str,
        domain: str,
        phase_outputs: Dict[str, Any],
    ) -> None:
        try:
            from aether_os.core.memory.fingerprinter import ProjectFingerprinter
            fp = ProjectFingerprinter()
            fingerprint = fp.fingerprint(raw_input, domain=domain)
            fp.store(
                run_id=run_id,
                org_id=org_id,
                fingerprint=fingerprint,
                phase_outputs=phase_outputs,
            )
        except Exception as exc:
            logger.debug("Fingerprinter store failed: %s", exc)

    async def _find_similar_runs(
        self,
        org_id: str,
        raw_input: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """Use fingerprinter + matcher to find similar past runs."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._sync_find_similar, org_id, raw_input, top_k
        )

    def _sync_find_similar(
        self,
        org_id: str,
        raw_input: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        try:
            from aether_os.core.memory.fingerprinter import ProjectFingerprinter
            from aether_os.core.memory.matcher import ProjectMatcher
            fp = ProjectFingerprinter()
            fingerprint = fp.fingerprint(raw_input)
            matcher = ProjectMatcher()
            return matcher.find_similar(
                fingerprint=fingerprint,
                org_id=org_id,
                top_k=top_k,
            )
        except Exception as exc:
            logger.debug("Matcher failed: %s", exc)
            return []

    # ── Session memory ────────────────────────────────────────────────────────

    async def get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """Load user preferences from the user_preferences JSON column."""
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import User
            session_factory = get_session_factory()
            async with session_factory() as session:
                user = await session.get(User, user_id)
                if user and user.user_preferences:
                    return json.loads(user.user_preferences)
        except Exception as exc:
            logger.debug("get_user_preferences failed: %s", exc)
        return {}

    async def set_user_preferences(self, user_id: str, prefs: Dict[str, Any]) -> None:
        """Persist user preferences to the user_preferences JSON column."""
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import User
            session_factory = get_session_factory()
            async with session_factory() as session:
                user = await session.get(User, user_id)
                if user:
                    # Merge with existing prefs rather than overwrite
                    existing = {}
                    if user.user_preferences:
                        try:
                            existing = json.loads(user.user_preferences)
                        except json.JSONDecodeError:
                            pass
                    existing.update(prefs)
                    user.user_preferences = json.dumps(existing)
                    await session.commit()
        except Exception as exc:
            logger.debug("set_user_preferences failed: %s", exc)

    # ── Graph RAG ─────────────────────────────────────────────────────────────

    async def build_repo_graph(self, project_dir: str) -> Dict[str, Any]:
        """Build symbol/call graph for a project directory (used by p02_architecture)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_build_graph, project_dir)

    def _sync_build_graph(self, project_dir: str) -> Dict[str, Any]:
        try:
            from aether_os.core.memory.graph_rag import GraphRAG
            rag = GraphRAG()
            return rag.analyze(project_dir)
        except Exception as exc:
            logger.debug("GraphRAG failed: %s", exc)
            return {}


_memory_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
