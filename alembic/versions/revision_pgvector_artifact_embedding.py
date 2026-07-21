"""Add pgvector VECTOR(1536) column to artifact_embeddings; JSON fallback at runtime.

NOTE: Before running this migration on the VPS, execute:
    CREATE EXTENSION IF NOT EXISTS vector;
in psql as superuser. This step is WAITING-ON-OPERATOR.
Local development: run `pip install pgvector` and ensure PostgreSQL has the extension.

Revision ID: revision_pgvector_artifact_embedding
Revises: add_updated_at_org_user
Create Date: 2026-07-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Use try/import so the migration file itself doesn't fail if pgvector isn't installed
try:
    from pgvector.sqlalchemy import Vector
    _HAS_PGVECTOR = True
except ImportError:
    _HAS_PGVECTOR = False

revision: str = 'revision_pgvector_artifact_embedding'
down_revision: Union[str, None] = 'add_updated_at_org_user'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if _HAS_PGVECTOR:
        op.add_column('artifact_embeddings',
            sa.Column('embedding_vector', Vector(1536), nullable=True))
        # ponytail: keep embedding JSON column for fallback until all data migrated
    else:
        import logging
        logging.getLogger(__name__).warning(
            "pgvector not installed — skipping VECTOR column addition. "
            "Run: pip install pgvector; then CREATE EXTENSION IF NOT EXISTS vector; "
            "then alembic upgrade heads"
        )


def downgrade() -> None:
    if _HAS_PGVECTOR:
        op.drop_column('artifact_embeddings', 'embedding_vector')
