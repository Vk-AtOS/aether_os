"""ChromaDB-backed vector store for project memory.

Provides semantic similarity search across past successful runs using
dense embeddings. Falls back to the SQLite fingerprint matcher if
chromadb or its dependencies are unavailable.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CHROMA_DIR = Path.home() / ".aether_os" / "chroma_memory"


class ChromaProjectMemory:
    """
    Semantic vector store for project descriptions.
    Uses ChromaDB with its built-in embedding function (all-MiniLM-L6-v2 via onnxruntime).
    Filtered by org_id so each tenant only sees their own history.
    """

    _instance: Optional["ChromaProjectMemory"] = None

    @classmethod
    def get_instance(cls) -> "ChromaProjectMemory":
        if cls._instance is None:
            cls._instance = ChromaProjectMemory()
        return cls._instance

    def __init__(self) -> None:
        self._collection = None
        try:
            import chromadb
            from chromadb.config import Settings

            _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(
                path=str(_CHROMA_DIR),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(
                name="project_memory",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("ChromaProjectMemory ready at %s (%d docs)", _CHROMA_DIR, self._collection.count())
        except ImportError:
            logger.info("chromadb not available — using SQLite fingerprint fallback")
        except Exception as exc:
            logger.warning("ChromaProjectMemory init failed (%s) — using fallback", exc)

    @property
    def available(self) -> bool:
        return self._collection is not None

    def store(
        self,
        run_id: str,
        org_id: str,
        raw_input: str,
        domain: str = "general",
        project_name: str = "",
        winning_approach: str = "",
    ) -> None:
        if not self.available or not raw_input.strip():
            return
        try:
            doc_id = f"{org_id}::{run_id}"
            self._collection.upsert(
                ids=[doc_id],
                documents=[raw_input],
                metadatas=[{
                    "run_id": run_id,
                    "org_id": org_id,
                    "domain": domain,
                    "project_name": project_name[:200],
                    "winning_approach": (winning_approach or "")[:500],
                }],
            )
            logger.debug("ChromaProjectMemory: stored run %s for org %s", run_id, org_id)
        except Exception as exc:
            logger.debug("ChromaProjectMemory.store failed: %s", exc)

    def search(
        self,
        org_id: str,
        query: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        if not self.available or not query.strip():
            return []
        try:
            n = self._collection.count()
            if n == 0:
                return []
            results = self._collection.query(
                query_texts=[query],
                n_results=min(top_k, n),
                where={"org_id": org_id} if n > 0 else None,
                include=["metadatas", "distances"],
            )
            matches = []
            ids_list = results.get("ids", [[]])[0]
            metas_list = results.get("metadatas", [[]])[0]
            dists_list = results.get("distances", [[]])[0]
            for doc_id, meta, dist in zip(ids_list, metas_list, dists_list):
                # ChromaDB cosine distance: 0 = identical, 2 = opposite → convert to similarity
                similarity = max(0.0, 1.0 - (dist / 2.0))
                matches.append({
                    "run_id": meta.get("run_id", doc_id.split("::")[-1]),
                    "org_id": meta.get("org_id", org_id),
                    "domain": meta.get("domain", "general"),
                    "project_name": meta.get("project_name", ""),
                    "winning_approach": meta.get("winning_approach", ""),
                    "similarity": round(similarity, 4),
                    "source": "chromadb",
                })
            return sorted(matches, key=lambda x: x["similarity"], reverse=True)
        except Exception as exc:
            logger.debug("ChromaProjectMemory.search failed: %s", exc)
            return []
