import os
import json
import logging
import sqlite3
import hashlib
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional

# AetherOS imports
try:
    from aether_os.core.llm.client import get_llm_client
except ImportError:
    # Handle imports when run directly or in different contexts
    pass

logger = logging.getLogger(__name__)

class ArtifactStore:
    """
    Semantic store for generated artifacts.
    Uses pure Python similarity calculation since sqlite-vec is unavailable.
    """
    def __init__(self):
        self.db_path = Path.home() / ".aether_os" / "aether_os.db"
        self._initialised = False

    def _get_connection(self):
        return sqlite3.connect(str(self.db_path))

    def init_db(self):
        """Initialise artifact tables."""
        if self._initialised:
            return
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifact_embeddings (
                    run_id TEXT,
                    file_path TEXT,
                    content_hash TEXT,
                    embedding_json TEXT,
                    PRIMARY KEY (run_id, file_path)
                )
            """)
            conn.commit()
        self._initialised = True

    async def store_artifact(self, run_id: str, file_path: str, content: str):
        """Embed and store a file's content."""
        self.init_db()
        # Truncate content to avoid token limits if necessary, though embed() should handle it
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        
        try:
            client = get_llm_client()
            embedding = await client.embed(content)
            
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO artifact_embeddings (run_id, file_path, content_hash, embedding_json)
                    VALUES (?, ?, ?, ?)
                """, (run_id, file_path, content_hash, json.dumps(embedding)))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to store artifact {file_path}: {e}")

    async def search(self, query: str, org_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Semantic search across artifacts for an org."""
        self.init_db()
        try:
            client = get_llm_client()
            query_vec = await client.embed(query)
            query_np = np.array(query_vec)
            
            results = []
            with self._get_connection() as conn:
                # Note: This is an O(N) scan. For a small project this is fine.
                # In production we would use pgvector or a specialized vector DB.
                stmt = """
                    SELECT a.run_id, a.file_path, a.embedding_json
                    FROM artifact_embeddings a
                    JOIN runs r ON a.run_id = r.id
                    WHERE r.org_id = ?
                """
                cursor = conn.execute(stmt, (org_id,))
                for run_id, file_path, embedding_json in cursor:
                    try:
                        embedding = np.array(json.loads(embedding_json))
                        # Cosine similarity
                        dot = np.dot(query_np, embedding)
                        norm_a = np.linalg.norm(query_np)
                        norm_b = np.linalg.norm(embedding)
                        if norm_a == 0 or norm_b == 0:
                            score = 0.0
                        else:
                            score = dot / (norm_a * norm_b)
                        
                        results.append({
                            "run_id": run_id,
                            "file_path": file_path,
                            "score": float(score)
                        })
                    except Exception as e:
                        logger.warning(f"Failed to process embedding for {file_path}: {e}")
                        continue
            
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def get_artifact(self, run_id: str, file_path: str) -> Optional[str]:
        """Retrieve artifact content from DB snapshots or filesystem."""
        try:
            # Try snapshots table first (SQLAlchemy)
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Snapshot
            from sqlalchemy import select
            
            # Note: We use a separate session here
            session_factory = get_session_factory()
            async with session_factory() as session:
                stmt = select(Snapshot).where(
                    Snapshot.run_id == run_id,
                    Snapshot.file_path == file_path
                )
                res = await session.execute(stmt)
                snap = res.scalar_one_or_none()
                if snap:
                    return snap.content
        except Exception as e:
            logger.debug("Failed to get artifact from DB: %s", e)

        # Fallback to filesystem
        try:
            project_dir = Path.home() / ".aether_os" / "projects" / run_id
            full_path = project_dir / file_path
            if full_path.exists() and full_path.is_file():
                return full_path.read_text()
        except Exception as e:
            logger.debug("Failed to get artifact from filesystem: %s", e)
            
        return None

    async def embed_run(self, run_id: str, org_id: str, project_dir: Path) -> int:
        """Embed all source files in project_dir and return the count stored."""
        extensions = {".py", ".js", ".ts", ".html", ".yml", ".json"}
        count = 0
        project_path = Path(project_dir)
        if not project_path.exists():
            return 0
        for f in project_path.rglob("*"):
            if f.is_file() and f.suffix in extensions:
                try:
                    await self.store_artifact(run_id, str(f.relative_to(project_path)), f.read_text())
                    count += 1
                    if count >= 50:
                        break
                except Exception as e:
                    logger.warning("embed_run: skipping %s: %s", f, e)
        return count


_store = None
def get_artifact_store():
    global _store
    if _store is None:
        _store = ArtifactStore()
    return _store
