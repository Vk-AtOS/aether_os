"""Vector search over artifact_embeddings: pgvector in SQL when it is really there, JSON scan otherwise.

pgvector is used only when ALL of these hold: the pgvector Python package is installed, the
database is PostgreSQL, the `vector` extension exists and artifact_embeddings.embedding_vector
exists. Anything else (SQLite development, no extension, a missing column, a vector of another
size) falls back to the JSON column, so a build without pgvector never breaks.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

try:
    from pgvector.sqlalchemy import Vector as _Vector  # noqa: F401
    _HAS_PGVECTOR = True
except ImportError:
    _HAS_PGVECTOR = False

EMBEDDING_DIM = 1536            # artifact_embeddings.embedding_vector is vector(1536)
JSON_SCAN_LIMIT = 2000          # newest rows ranked in Python when pgvector is unavailable

_READY: Dict[str, bool] = {}    # per database URL: the extension and column checks cost a query each


def literal(vector: List[float]) -> str:
    """pgvector text form: '[0.1,0.2,...]'."""
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


async def pgvector_ready(session: AsyncSession) -> bool:
    if not _HAS_PGVECTOR:
        return False
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return False
    key = str(bind.url)
    if key not in _READY:
        row = (await session.execute(text(
            "SELECT (SELECT count(*) FROM pg_extension WHERE extname = 'vector') > 0 AND "
            "(SELECT count(*) FROM information_schema.columns WHERE table_name = 'artifact_embeddings' "
            "AND column_name = 'embedding_vector') > 0"
        ))).scalar()
        _READY[key] = bool(row)
        if not _READY[key]:
            logger.warning("pgvector not active (extension or embedding_vector column missing): using JSON scan")
    return _READY[key]


async def write_vector(session: AsyncSession, row_id: str, vector: List[float]) -> bool:
    """Store the pgvector copy of an embedding. False (nothing written) when pgvector is not usable."""
    if len(vector) != EMBEDDING_DIM or not await pgvector_ready(session):
        return False
    await session.execute(
        text("UPDATE artifact_embeddings SET embedding_vector = CAST(:v AS vector) WHERE id = :id"),
        {"v": literal(vector), "id": row_id},
    )
    return True


async def search(session: AsyncSession, org_id: str, query: List[float], limit: int) -> Optional[List[Dict[str, Any]]]:
    """Nearest artifacts of an org by cosine distance in SQL, or None when pgvector cannot answer
    (the caller then falls back to the JSON scan). Rows without a vector are not returned."""
    if len(query) != EMBEDDING_DIM or not await pgvector_ready(session):
        return None
    rows = (await session.execute(
        text(
            "SELECT run_id, file_path, 1 - (embedding_vector <=> CAST(:q AS vector)) AS score "
            "FROM artifact_embeddings WHERE org_id = :org AND embedding_vector IS NOT NULL "
            "ORDER BY embedding_vector <=> CAST(:q AS vector) LIMIT :lim"
        ),
        {"q": literal(query), "org": org_id, "lim": limit},
    )).all()
    return [{"run_id": r[0], "file_path": r[1], "score": float(r[2])} for r in rows]
