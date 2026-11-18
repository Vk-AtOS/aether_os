"""KAN-179/188: vector search uses pgvector when it is really active and falls back safely otherwise."""
import asyncio
import os
import uuid

import pytest
from sqlalchemy import text

from aether_os.core import vector_store
from aether_os.core.artifact_store import ArtifactStore
from aether_os.core.db import get_session_factory
from aether_os.core.models import ArtifactEmbedding


def _vec(i, n=8):
    v = [0.0] * n
    v[i % n] = 1.0
    return v


def test_literal_is_pgvector_text_form():
    assert vector_store.literal([1, 0.5]) == "[1.0,0.5]"


def test_sqlite_has_no_pgvector_and_search_returns_none(gw):
    async def go():
        async with get_session_factory()() as s:
            assert await vector_store.pgvector_ready(s) is False
            assert await vector_store.search(s, "o", [0.0] * vector_store.EMBEDDING_DIM, 3) is None
            assert await vector_store.write_vector(s, "x", [0.0] * vector_store.EMBEDDING_DIM) is False
    asyncio.run(go())


def test_json_fallback_ranks_all_rows_of_the_org_not_an_arbitrary_few(gw):
    org = gw.register("vecorg").org_id

    async def go():
        async with get_session_factory()() as s:
            for i in range(60):          # the old query looked at fetch_limit (= limit*4) rows only
                s.add(ArtifactEmbedding(id=str(uuid.uuid4()), run_id=f"r{i}", org_id=org, file_path=f"f{i}.py",
                                        content_hash="h", embedding=_vec(i)))
            await s.commit()
        import numpy as np
        hits = await ArtifactStore()._semantic_search(org, np.array(_vec(3)), 8)
        return sorted(hits, key=lambda h: -h["score"])[0]
    best = asyncio.run(go())
    assert best["score"] == pytest.approx(1.0)


@pytest.mark.skipif(not os.environ.get("AETHER_PG_VECTOR_TEST_URL"),
                    reason="needs AETHER_PG_VECTOR_TEST_URL=postgresql+asyncpg://... on a server with the pgvector extension "
                           "(and the pgvector Python package): UNVERIFIED until run once")
def test_postgres_search_orders_by_vector_distance_and_uses_the_index():
    from sqlalchemy.ext.asyncio import create_async_engine

    async def go():
        eng = create_async_engine(os.environ["AETHER_PG_VECTOR_TEST_URL"])
        dim = vector_store.EMBEDDING_DIM
        async with eng.begin() as c:
            await c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await c.execute(text("DROP TABLE IF EXISTS artifact_embeddings"))
            await c.execute(text("CREATE TABLE artifact_embeddings (id text primary key, run_id text, org_id text, "
                                 "file_path text, embedding_vector vector(%d))" % dim))
            await c.execute(text("CREATE INDEX ix_v ON artifact_embeddings USING hnsw (embedding_vector vector_cosine_ops)"))
            for i in range(5):
                v = [0.0] * dim
                v[i] = 1.0
                await c.execute(text("INSERT INTO artifact_embeddings VALUES (:i, 'r', 'o', :f, CAST(:v AS vector))"),
                                {"i": str(i), "f": f"f{i}", "v": vector_store.literal(v)})
        from sqlalchemy.ext.asyncio import AsyncSession
        async with AsyncSession(eng) as s:
            vector_store._READY.clear()
            q = [0.0] * dim
            q[2] = 1.0
            hits = await vector_store.search(s, "o", q, 3)
            assert hits[0]["file_path"] == "f2" and hits[0]["score"] == pytest.approx(1.0)
            plan = (await s.execute(text("SET enable_seqscan = off"))) and (await s.execute(text(
                "EXPLAIN SELECT id FROM artifact_embeddings ORDER BY embedding_vector <=> CAST(:q AS vector) LIMIT 3"),
                {"q": vector_store.literal(q)})).all()
            assert any("ix_v" in row[0] for row in plan)
        await eng.dispose()
    asyncio.run(go())
