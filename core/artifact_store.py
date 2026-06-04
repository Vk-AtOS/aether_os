import asyncio
import hashlib
import json
import logging
import uuid
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
    Semantic store for generated artifacts backed by PostgreSQL (artifact_embeddings table).
    Falls back to text search when embeddings are unavailable.
    """

    async def store_artifact(
        self,
        run_id: str,
        file_path: str,
        content: str,
        org_id: Optional[str] = None,
    ) -> None:
        """Embed and upsert a file's content into artifact_embeddings."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        try:
            client = get_llm_client()
            embedding = await client.embed(content)
            if not embedding or all(v == 0.0 for v in embedding):
                logger.warning(
                    "Skipping embedding for artifact '%s': zero-vector received (Ollama may be down)",
                    file_path,
                )
                return
        except Exception as exc:
            logger.error("Failed to embed artifact %s: %s", file_path, exc)
            return

        resolved_org_id = org_id or await self._lookup_org_id(run_id)
        if not resolved_org_id:
            logger.warning("store_artifact: cannot resolve org_id for run %s — skipping", run_id)
            return

        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import ArtifactEmbedding
            from sqlalchemy import select

            sf = get_session_factory()
            async with sf() as session:
                stmt = select(ArtifactEmbedding).where(
                    ArtifactEmbedding.run_id == run_id,
                    ArtifactEmbedding.file_path == file_path,
                )
                existing = (await session.execute(stmt)).scalar_one_or_none()
                if existing:
                    existing.content_hash = content_hash
                    existing.embedding = embedding
                else:
                    session.add(ArtifactEmbedding(
                        id=str(uuid.uuid4()),
                        run_id=run_id,
                        org_id=resolved_org_id,
                        file_path=file_path,
                        content_hash=content_hash,
                        embedding=embedding,
                    ))
                await session.commit()
        except Exception as exc:
            logger.error("Failed to store artifact %s: %s", file_path, exc)

    async def _lookup_org_id(self, run_id: str) -> Optional[str]:
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Run
            from sqlalchemy import select
            sf = get_session_factory()
            async with sf() as session:
                run = (await session.execute(
                    select(Run.org_id).where(Run.id == run_id)
                )).scalar_one_or_none()
                return run
        except Exception as exc:
            logger.debug("_lookup_org_id failed for %s: %s", run_id, exc)
            return None

    async def search(self, query: str, org_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search artifacts for an org — semantic with text fallback."""
        try:
            client = get_llm_client()
            query_vec = await client.embed(query)
            query_np = np.array(query_vec)
            results = await self._semantic_search(org_id, query_np, limit * 4)
            results.sort(key=lambda x: x["score"], reverse=True)
            if results:
                return results[:limit]
        except Exception as exc:
            logger.warning("Semantic search failed, falling back to text: %s", exc)

        return await self._text_search(query, org_id, limit)

    async def _semantic_search(
        self, org_id: str, query_np: Any, fetch_limit: int
    ) -> List[Dict[str, Any]]:
        from aether_os.core.db import get_session_factory
        from aether_os.core.models import ArtifactEmbedding
        from sqlalchemy import select

        sf = get_session_factory()
        async with sf() as session:
            rows = (await session.execute(
                select(ArtifactEmbedding.run_id, ArtifactEmbedding.file_path, ArtifactEmbedding.embedding)
                .where(ArtifactEmbedding.org_id == org_id)
                .limit(fetch_limit)
            )).all()

        results = []
        for row_run_id, row_file_path, embedding_data in rows:
            try:
                emb = np.array(embedding_data if isinstance(embedding_data, list) else json.loads(embedding_data))
                dot = np.dot(query_np, emb)
                norm_a = np.linalg.norm(query_np)
                norm_b = np.linalg.norm(emb)
                score = float(dot / (norm_a * norm_b)) if norm_a and norm_b else 0.0
                results.append({"run_id": row_run_id, "file_path": row_file_path, "score": score})
            except Exception as exc:
                logger.warning("Failed to process embedding for %s: %s", row_file_path, exc)
        return results

    async def _text_search(self, query: str, org_id: str, limit: int) -> List[Dict[str, Any]]:
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
                runs = (await session.execute(stmt)).scalars().all()

            results = []
            for run in runs:
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
            sf = get_session_factory()
            async with sf() as session:
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
        _skip_dirs = {"node_modules", ".git", "__pycache__", "dist", "build", ".venv", "venv"}
        count = 0
        project_path = Path(project_dir)
        if not project_path.exists():
            return 0
        for f in project_path.rglob("*"):
            if any(part in _skip_dirs for part in f.parts):
                continue
            if f.is_file() and f.suffix in extensions:
                try:
                    await self.store_artifact(
                        run_id, str(f.relative_to(project_path)), f.read_text(), org_id=org_id
                    )
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
