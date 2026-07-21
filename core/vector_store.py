"""Runtime adapter: pgvector VECTOR column when available, JSON array fallback.

Usage:
    store = VectorStore(db_session)
    store.upsert(artifact_id, embedding_list)
    results = await store.search(query_vector, limit=10)
"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

try:
    from pgvector.sqlalchemy import Vector as _Vector  # noqa: F401
    _HAS_PGVECTOR = True
except ImportError:
    _HAS_PGVECTOR = False


class VectorStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def upsert(self, artifact_id: str, vector: list[float]) -> None:
        """Save embedding to pgvector column if available, else to JSON column."""
        from core.models import ArtifactEmbedding
        row = self._db.get(ArtifactEmbedding, artifact_id)
        if row is None:
            logger.warning("VectorStore.upsert: artifact_id %s not found", artifact_id)
            return
        if _HAS_PGVECTOR:
            row.embedding_vector = vector
        else:
            row.embedding = vector  # JSON fallback
        self._db.commit()

    def search(self, query_vector: list[float], limit: int = 10) -> list[str]:
        """Cosine similarity search via pgvector (<=> operator).

        Returns a list of artifact_embedding IDs ordered by similarity.
        # ponytail: JSON fallback search is O(n) full scan — use pgvector once extension installed
        """
        if not _HAS_PGVECTOR:
            logger.warning(
                "VectorStore.search: pgvector not installed — returning empty. "
                "Run: pip install pgvector + CREATE EXTENSION vector; alembic upgrade heads"
            )
            return []
        try:
            rows = self._db.execute(
                text(
                    "SELECT id FROM artifact_embeddings "
                    "WHERE embedding_vector IS NOT NULL "
                    "ORDER BY embedding_vector <=> cast(:vec AS vector) "
                    "LIMIT :lim"
                ),
                {"vec": str(query_vector), "lim": limit},
            ).fetchall()
            return [r[0] for r in rows]
        except Exception as exc:
            logger.warning("VectorStore.search failed: %s", exc)
            return []
