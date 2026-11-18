"""Add pgvector VECTOR(1536) column to artifact_embeddings; JSON fallback at runtime.

The migration creates the extension itself when the database role may (otherwise ask the
operator to enable the vector extension as superuser and re-run it); without the extension
nothing breaks, search just stays on the JSON column. It no longer needs the pgvector Python
package: the column is plain SQL.

Revision ID: revision_pgvector_artifact_embedding
Revises: add_updated_at_org_user
Create Date: 2026-07-22
"""
from typing import Sequence, Union

from alembic import op

try:   # one definition shared with the empty-database bootstrap (core/schema_ddl.py)
    from aether_os.core import schema_ddl
except ModuleNotFoundError:   # alembic run from the repository root without PYTHONPATH (alembic.ini prepends ".")
    from core import schema_ddl

revision: str = 'revision_pgvector_artifact_embedding'
down_revision: Union[str, None] = 'add_updated_at_org_user'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite and others keep the JSON column only; so does a PostgreSQL server without pgvector.
    schema_ddl.apply(op.get_bind(), only=(schema_ddl.PGVECTOR,))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE artifact_embeddings DROP COLUMN IF EXISTS embedding_vector")
