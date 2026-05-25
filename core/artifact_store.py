import asyncio
import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

try:
    from aether_os.core.llm.client import get_llm_client
except ImportError:
    pass

logger = logging.getLogger(__name__)


class ArtifactStore:
    """
    Semantic store for generated artifacts.
    All sqlite3 I/O is wrapped in asyncio.to_thread() to avoid blocking the event loop.
    """

    def __init__(self):
        self.db_path = Path.home() / ".aether_os" / "aether_os.db"
        self._initialised = False

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db_sync(self) -> None:
        if self._initialised:
            return
        with self._get_connection() as conn:
            # Migrate old schema that used id TEXT PRIMARY KEY (incompatible with current code)
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='artifact_embeddings'"
            )
            if cur.fetchone():
                col_cur = conn.execute("PRAGMA table_info(artifact_embeddings)")
                cols = [row[1] for row in col_cur.fetchall()]
                if "id" in cols:
                    conn.execute("DROP TABLE artifact_embeddings")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifact_embeddings (
                    run_id TEXT,
                    file_path TEXT,
                    content_hash TEXT,
                    embedding TEXT,
                    PRIMARY KEY (run_id, file_path)
                )
            """)
            conn.commit()
        self._initialised = True

    async def _ensure_init(self) -> None:
        if not self._initialised:
            await asyncio.to_thread(self._init_db_sync)

    def _store_artifact_sync(self, run_id: str, file_path: str, content_hash: str, embedding: List[float]) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO artifact_embeddings (run_id, file_path, content_hash, embedding)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, file_path, content_hash, json.dumps(embedding)),
            )
            conn.commit()

    async def store_artifact(self, run_id: str, file_path: str, content: str) -> None:
        """Embed and store a file's content."""
        await self._ensure_init()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        try:
            client = get_llm_client()
            embedding = await client.embed(content)
            # PIPELINE-033: warn explicitly when zero-vector received (Ollama may be down)
            if not embedding or all(v == 0.0 for v in embedding):
                logger.warning(
                    "Skipping embedding for artifact '%s': zero-vector received (Ollama may be down)",
                    file_path,
                )
                return
            await asyncio.to_thread(self._store_artifact_sync, run_id, file_path, content_hash, embedding)
        except Exception as exc:
            logger.error("Failed to store artifact %s: %s", file_path, exc)

    def _search_sync(self, org_id: str, query_np: Any) -> List[Dict[str, Any]]:
        results = []
        with self._get_connection() as conn:
            stmt = """
                SELECT a.run_id, a.file_path, a.embedding
                FROM artifact_embeddings a
                JOIN runs r ON a.run_id = r.id
                WHERE r.org_id = ?
            """
            cursor = conn.execute(stmt, (org_id,))
            for row_run_id, row_file_path, embedding_json in cursor:
                try:
                    emb = np.array(json.loads(embedding_json))
                    dot = np.dot(query_np, emb)
                    norm_a = np.linalg.norm(query_np)
                    norm_b = np.linalg.norm(emb)
                    score = float(dot / (norm_a * norm_b)) if norm_a and norm_b else 0.0
                    results.append({"run_id": row_run_id, "file_path": row_file_path, "score": score})
                except Exception as exc:
                    logger.warning("Failed to process embedding for %s: %s", row_file_path, exc)
        return results

    async def search(self, query: str, org_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search artifacts for an org — semantic with text fallback."""
        await self._ensure_init()
        # Try semantic search first
        try:
            client = get_llm_client()
            query_vec = await client.embed(query)
            query_np = np.array(query_vec)
            results = await asyncio.to_thread(self._search_sync, org_id, query_np)
            results.sort(key=lambda x: x["score"], reverse=True)
            if results:
                return results[:limit]
        except Exception as exc:
            logger.warning("Semantic search failed, falling back to text: %s", exc)

        # Text fallback: search runs table by project_name/client_id/status
        return await self._text_search(query, org_id, limit)

    async def _text_search(self, query: str, org_id: str, limit: int) -> List[Dict[str, Any]]:
        """Full-text search over runs by project_name, client_id, status."""
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Run
            from sqlalchemy import select, or_
            sf = get_session_factory()
            q_lower = f"%{query.lower()}%"
            async with sf() as session:
                stmt = (
                    select(Run)
                    .where(Run.org_id == org_id)
                    .where(
                        or_(
                            Run.project_name.ilike(q_lower),
                            Run.client_id.ilike(q_lower),
                            Run.status.ilike(q_lower),
                        )
                    )
                    .limit(limit)
                )
                rows = (await session.execute(stmt)).scalars().all()
            results = []
            for run in rows:
                project_dir = Path.home() / ".aether_os" / "projects" / run.id
                results.append({
                    "run_id": run.id,
                    "project_name": run.project_name,
                    "status": run.status,
                    "client_id": run.client_id or "",
                    "requirement": run.requirement or run.raw_input or "",
                    "domain": run.domain or "general",
                    "file_path": "project",
                    "score": 1.0,
                    "type": "run",
                })
                # Also search artifact files on disk
                for suffix in (".md", ".json"):
                    for fpath in sorted(project_dir.rglob(f"*{suffix}"))[:5]:
                        try:
                            text = fpath.read_text(errors="ignore").lower()
                            if query.lower() in text:
                                results.append({
                                    "run_id": run.id,
                                    "project_name": run.project_name,
                                    "status": run.status,
                                    "file_path": str(fpath.relative_to(project_dir)),
                                    "score": 0.8,
                                    "type": "artifact",
                                })
                        except Exception:
                            pass
            return results[:limit]
        except Exception as exc:
            logger.error("Text search failed: %s", exc)
            return []

    async def get_artifact(self, run_id: str, file_path: str) -> Optional[str]:
        """Retrieve artifact content from DB snapshots or filesystem."""
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Snapshot
            from sqlalchemy import select
            session_factory = get_session_factory()
            async with session_factory() as session:
                snap = (await session.execute(
                    select(Snapshot).where(Snapshot.run_id == run_id, Snapshot.file_path == file_path)
                )).scalar_one_or_none()
                if snap:
                    return snap.content
        except Exception as exc:
            logger.debug("Failed to get artifact from DB: %s", exc)

        try:
            full_path = Path.home() / ".aether_os" / "projects" / run_id / file_path
            if full_path.exists() and full_path.is_file():
                return full_path.read_text()
        except Exception as exc:
            logger.debug("Failed to get artifact from filesystem: %s", exc)
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
                except Exception as exc:
                    logger.warning("embed_run: skipping %s: %s", f, exc)
        return count


_store = None


def get_artifact_store() -> ArtifactStore:
    global _store
    if _store is None:
        _store = ArtifactStore()
    return _store
