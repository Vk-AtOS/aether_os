"""Backfill artifact_embeddings.embedding_vector from the JSON column and index it (KAN-179).

Only does anything on PostgreSQL where the pgvector extension and the embedding_vector column
exist; otherwise a no-op, so the revision is safe everywhere. Rows whose JSON is not a
1536-number array are left alone (they stay searchable through the JSON fallback).

Revision ID: pgvector_backfill_and_index
Revises: unique_keys_plugins_learning_feedback_golden
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

try:   # one definition shared with the empty-database bootstrap (core/schema_ddl.py)
    from aether_os.core import schema_ddl
except ModuleNotFoundError:   # alembic run from the repository root without PYTHONPATH (alembic.ini prepends ".")
    from core import schema_ddl

revision: str = 'pgvector_backfill_and_index'
down_revision: Union[str, None] = 'unique_keys_plugins_learning_feedback_golden'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _active(bind) -> bool:
    if bind.dialect.name != "postgresql":
        return False
    return bool(bind.execute(sa.text(
        "SELECT (SELECT count(*) FROM pg_extension WHERE extname = 'vector') > 0 AND "
        "(SELECT count(*) FROM information_schema.columns WHERE table_name = 'artifact_embeddings' "
        "AND column_name = 'embedding_vector') > 0"
    )).scalar())


def upgrade() -> None:
    bind = op.get_bind()
    if not _active(bind):
        return
    # The JSON array text '[0.1, 0.2, ...]' is also valid vector input.
    op.execute(
        "UPDATE artifact_embeddings SET embedding_vector = CAST(CAST(embedding AS text) AS vector) "
        "WHERE embedding_vector IS NULL AND embedding IS NOT NULL "
        "AND json_typeof(embedding::json) = 'array' AND json_array_length(embedding::json) = 1536"
    )
    schema_ddl.ensure_pgvector(bind)   # the cosine index (extension and column are already there)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_artifact_embeddings_vector_cosine")
