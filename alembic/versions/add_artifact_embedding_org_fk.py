"""add org_id FK to artifact_embeddings

Revision ID: add_artifact_embedding_org_fk
Revises: revision_guardian_module
Create Date: 2026-05-30
"""
from alembic import op

revision = 'add_artifact_embedding_org_fk'
down_revision = 'revision_guardian_module'
branch_labels = None
depends_on = None


def upgrade():
    op.create_foreign_key(
        'fk_artifact_embeddings_org_id',
        'artifact_embeddings', 'organisations',
        ['org_id'], ['id'],
        ondelete='CASCADE'
    )


def downgrade():
    op.drop_constraint('fk_artifact_embeddings_org_id', 'artifact_embeddings', type_='foreignkey')
