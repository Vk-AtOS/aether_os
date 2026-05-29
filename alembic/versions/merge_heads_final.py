"""merge duplicate heads: revision_add_org_api_keys + revision_add_artifact_embedding_org_id

Revision ID: merge_heads_final
Revises: revision_add_org_api_keys, revision_add_artifact_embedding_org_id
Create Date: 2026-05-29 00:00:00.000000
"""
from alembic import op

revision = "merge_heads_final"
down_revision = ("revision_add_org_api_keys", "revision_add_artifact_embedding_org_id")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
