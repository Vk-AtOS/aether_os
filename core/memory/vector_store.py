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


def _org_collection_name(org_id: str) -> str:
    """Sanitise org_id into a valid ChromaDB collection name (alphanumeric + underscores)."""
    import re
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", org_id or "default")
    return f"org_{clean[:40]}"


class ChromaProjectMemory:
    """
    Semantic vector store for project descriptions, partitioned per org.
    Each org_id gets its own ChromaDB collection for strict tenant isolation.
    Uses ChromaDB with its built-in embedding function (all-MiniLM-L6-v2 via onnxruntime).
    """

    _instance: Optional["ChromaProjectMemory"] = None
    _client: Any = None  # shared PersistentClient

    @classmethod
    def get_instance(cls) -> "ChromaProjectMemory":
        if cls._instance is None:
            cls._instance = ChromaProjectMemory()
        return cls._instance

    def __init__(self) -> None:
        self._client = None
        try:
            import chromadb
            from chromadb.config import Settings
            _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(_CHROMA_DIR),
                settings=Settings(anonymized_telemetry=False),
            )
            logger.info("ChromaProjectMemory ready at %s", _CHROMA_DIR)
        except ImportError:
            logger.info("chromadb not available — using SQLite fingerprint fallback")
        except Exception as exc:
            logger.warning("ChromaProjectMemory init failed (%s) — using fallback", exc)

    @property
    def available(self) -> bool:
        return self._client is not None

    def _collection_for(self, org_id: str):
        """Return (or create) the per-org collection. Returns None on error."""
        if not self._client:
            return None
        try:
            return self._client.get_or_create_collection(
                name=_org_collection_name(org_id),
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:
            logger.debug("ChromaProjectMemory._collection_for(%s) failed: %s", org_id, exc)
            return None

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
        col = self._collection_for(org_id)
        if col is None:
            return
        try:
            col.upsert(
                ids=[run_id],
                documents=[raw_input],
                metadatas=[{
                    "run_id": run_id,
                    "org_id": org_id,
                    "domain": domain,
                    "project_name": project_name[:200],
                    "winning_approach": (winning_approach or "")[:500],
                }],
            )
            logger.debug("ChromaProjectMemory: stored run %s org %s", run_id, org_id)
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
        col = self._collection_for(org_id)
        if col is None:
            return []
        try:
            n = col.count()
            if n == 0:
                return []
            results = col.query(
                query_texts=[query],
                n_results=min(top_k, n),
                include=["metadatas", "distances"],
            )
            matches = []
            ids_list = results.get("ids", [[]])[0]
            metas_list = results.get("metadatas", [[]])[0]
            dists_list = results.get("distances", [[]])[0]
            for run_id_r, meta, dist in zip(ids_list, metas_list, dists_list):
                similarity = max(0.0, 1.0 - (dist / 2.0))
                matches.append({
                    "run_id": meta.get("run_id", run_id_r),
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
