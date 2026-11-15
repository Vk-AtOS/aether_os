"""Add pgvector VECTOR(1536) column to artifact_embeddings; JSON fallback at runtime.

The migration creates the extension itself when the database role may (otherwise ask the
operator to run `CREATE EXTENSION vector;` as superuser and re-run it); without the extension
nothing breaks, search just stays on the JSON column. It no longer needs the pgvector Python
package: the column is plain SQL.

Revision ID: revision_pgvector_artifact_embedding
Revises: add_updated_at_org_user
Create Date: 2026-07-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'revision_pgvector_artifact_embedding'
down_revision: Union[str, None] = 'add_updated_at_org_user'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _vector_extension_available(bind) -> bool:
    """CREATE EXTENSION inside a savepoint, so a server without pgvector (or a role that may not
    create extensions) leaves the migration running instead of aborting it."""
    try:
        with bind.begin_nested():
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        return True
    except sa.exc.DBAPIError as exc:
        import logging
        logging.getLogger(__name__).warning(
            "pgvector extension not available (%s): artifact search stays on the JSON column", exc.orig)
        return False


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite and others keep the JSON column only
    if _vector_extension_available(bind):
        # IF NOT EXISTS: the column may already be there (init_db / an earlier run of this revision).
        op.execute("ALTER TABLE artifact_embeddings ADD COLUMN IF NOT EXISTS embedding_vector vector(1536)")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE artifact_embeddings DROP COLUMN IF EXISTS embedding_vector")
