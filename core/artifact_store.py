import asyncio
import hashlib
import time
import io
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from aether_os.core import vector_store
from aether_os.core.run_app import safe_fs

logger = logging.getLogger(__name__)

try:
    from aether_os.core.llm.client import get_llm_client
except ImportError as e:
    logger.debug("LLM client unavailable, embeddings disabled: %s", e)

_S3_BUCKET = os.environ.get("S3_BUCKET", "")
_S3_PREFIX = "runs"
_SKIP_DIRS = {"node_modules", ".git", "__pycache__", "dist", "build", ".venv", "venv"}
_UPLOAD_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".md", ".sql", ".yml", ".yaml", ".sh", ".txt"}


SNAPSHOT_MAX_BYTES = 200_000
SNAPSHOT_MAX_PER_RUN = 500


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
        """Record a snapshot of the file, then embed and upsert its content into artifact_embeddings."""
        await self.record_snapshot(run_id, file_path, content)     # independent of the embedder being up
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
                    row_id = existing.id
                else:
                    row_id = str(uuid.uuid4())
                    session.add(ArtifactEmbedding(
                        id=row_id,
                        run_id=run_id,
                        org_id=resolved_org_id,
                        file_path=file_path,
                        content_hash=content_hash,
                        embedding=embedding,
                    ))
                await session.flush()
                # The JSON column stays the source of truth; the vector copy is what SQL search ranks.
                await vector_store.write_vector(session, row_id, embedding)
                await session.commit()
        except Exception as exc:
            logger.error("Failed to store artifact %s: %s", file_path, exc)

    async def record_snapshot(self, run_id: str, file_path: str, content: str) -> bool:
        """Append a Snapshot row (the run's file history) unless the newest one for this path is identical.

        Root cause of the always-empty Snapshots tab: nothing ever wrote Snapshot rows. Bounded: files over
        SNAPSHOT_MAX_BYTES are not kept and a run keeps at most SNAPSHOT_MAX_PER_RUN rows.
        """
        if not content or len(content.encode()) > SNAPSHOT_MAX_BYTES:
            return False
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Snapshot
            from sqlalchemy import func, select
            async with get_session_factory()() as session:
                last = (await session.execute(
                    select(Snapshot.content).where(Snapshot.run_id == run_id, Snapshot.file_path == file_path)
                    .order_by(Snapshot.created_at.desc()).limit(1))).scalar_one_or_none()
                if last == content:
                    return False
                n = (await session.execute(select(func.count()).select_from(Snapshot).where(Snapshot.run_id == run_id))).scalar_one()
                if n >= SNAPSHOT_MAX_PER_RUN:
                    return False
                session.add(Snapshot(run_id=run_id, file_path=file_path, content=content, created_at=time.time()))
                await session.commit()
            return True
        except Exception as exc:
            logger.warning("record_snapshot failed for %s: %s", file_path, exc)
            return False

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
            nearest = await vector_store.search(session, org_id, [float(x) for x in query_np], fetch_limit)
            if nearest is not None:
                return nearest
            # JSON fallback: rank the newest rows (it used to rank an arbitrary few, with no ORDER BY).
            rows = (await session.execute(
                select(ArtifactEmbedding.run_id, ArtifactEmbedding.file_path, ArtifactEmbedding.embedding)
                .where(ArtifactEmbedding.org_id == org_id)
                .order_by(ArtifactEmbedding.created_at.desc())
                .limit(max(fetch_limit, vector_store.JSON_SCAN_LIMIT))
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
                    for fpath in [f for f in safe_fs.walk_files(project_dir) if f.suffix == suffix][:5]:
                        try:
                            text = (safe_fs.read_text_or_none(project_dir, fpath) or "").lower()
                            if query.lower() in text:
                                results.append({
                                    "run_id": run.id,
                                    "project_name": run.project_name,
                                    "status": run.status,
                                    "file_path": str(fpath),
                                    "score": 0.8,
                                    "type": "artifact",
                                })
                        except Exception as exc:
                            logger.debug("Artifact file scan error: %s", exc)
            return results[:limit]
        except Exception as exc:
            logger.error("Text search failed: %s", exc)
            return []

    async def get_artifact(self, run_id: str, file_path: str) -> Optional[str]:
        """Retrieve artifact content from DB snapshots, filesystem, or S3."""
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
            project_dir = Path.home() / ".aether_os" / "projects" / run_id
            text = safe_fs.read_text_or_none(project_dir, file_path)   # no links, stays inside the project
            if text is not None:
                return text
        except Exception as exc:
            logger.debug("Failed to get artifact from filesystem: %s", exc)

        # Fall back to S3 if configured
        if _S3_BUCKET:
            try:
                content = await asyncio.to_thread(self._s3_download_text, run_id, file_path)
                if content is not None:
                    return content
            except Exception as exc:
                logger.debug("Failed to get artifact from S3: %s", exc)
        return None

    def _s3_client(self):
        import boto3
        return boto3.client(
            "s3",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )

    def _s3_key(self, run_id: str, relative_path: str) -> str:
        return f"{_S3_PREFIX}/{run_id}/{relative_path}"

    def _s3_download_text(self, run_id: str, file_path: str) -> Optional[str]:
        try:
            s3 = self._s3_client()
            obj = s3.get_object(Bucket=_S3_BUCKET, Key=self._s3_key(run_id, file_path))
            return obj["Body"].read().decode("utf-8", errors="replace")
        except Exception as exc:
            logger.debug("S3 download failed for %s/%s: %s", run_id, file_path, exc)
            return None

    async def upload_run_to_s3(self, run_id: str, project_dir: Path) -> int:
        """Upload all text artifacts from project_dir to S3. Returns count uploaded."""
        if not _S3_BUCKET:
            logger.debug("[s3] S3_BUCKET not set — skipping upload for run %s", run_id)
            return 0
        return await asyncio.to_thread(self._upload_run_sync, run_id, project_dir)

    def _upload_run_sync(self, run_id: str, project_dir: Path) -> int:
        try:
            s3 = self._s3_client()
            count = 0
            for f in safe_fs.walk_files(project_dir, skip_dirs=_SKIP_DIRS):
                if f.suffix not in _UPLOAD_EXTS:
                    continue
                rel = str(f)
                data = safe_fs.read_bytes_or_none(project_dir, f, max_bytes=5 * 1024 * 1024)  # skip links, > 5 MB
                if data is None:
                    continue
                key = self._s3_key(run_id, rel)
                try:
                    s3.upload_fileobj(io.BytesIO(data), _S3_BUCKET, key)
                    count += 1
                except Exception as exc:
                    logger.debug("[s3] upload failed for %s: %s", rel, exc)
            logger.info("[s3] Uploaded %d artifacts for run %s to s3://%s/%s/%s/",
                        count, run_id, _S3_BUCKET, _S3_PREFIX, run_id)
            return count
        except Exception as exc:
            logger.warning("[s3] upload_run_sync failed for run %s: %s", run_id, exc)
            return 0

    async def embed_run(self, run_id: str, org_id: str, project_dir: Path) -> int:
        """Embed all source files in project_dir and return the count stored."""
        extensions = {".py", ".js", ".ts", ".html", ".yml", ".json"}
        _skip_dirs = {"node_modules", ".git", "__pycache__", "dist", "build", ".venv", "venv"}
        count = 0
        project_path = Path(project_dir)
        if not project_path.exists():
            return 0
        for f in safe_fs.walk_files(project_path, skip_dirs=_skip_dirs):
            if f.suffix in extensions:
                try:
                    text = safe_fs.read_text_or_none(project_path, f)
                    if text is None:
                        continue
                    await self.store_artifact(run_id, str(f), text, org_id=org_id)
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
