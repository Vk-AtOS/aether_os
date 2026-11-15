"""add_artifact_embedding_org_id_index

Revision ID: revision_add_artifact_embedding_org_id
Revises: revision_add_quality_score_runs
Create Date: 2026-05-25 00:00:00.000000

The artifact_embeddings.org_id column was created in migration 3815540c9443 but
without an explicit index.  This migration adds the index for tenant-isolation
query performance and documents the column's purpose (DB-002).
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'revision_add_artifact_embedding_org_id'
down_revision: Union[str, None] = 'revision_add_quality_score_runs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The org_id column already exists (added in 3815540c9443); only the index is missing.
    op.create_index(
        'ix_artifact_embeddings_org_id',
        'artifact_embeddings',
        ['org_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_artifact_embeddings_org_id', table_name='artifact_embeddings')
