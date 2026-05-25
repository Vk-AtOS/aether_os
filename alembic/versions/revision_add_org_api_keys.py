"""add org_api_keys table for per-org LLM key storage

Revision ID: revision_add_org_api_keys
Revises: revision_add_quality_score_runs
Create Date: 2026-05-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision: str = 'revision_add_org_api_keys'
down_revision: str = 'revision_add_artifact_embedding_org_id'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'org_api_keys',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(36), nullable=False),
        sa.Column('provider', sa.String(64), nullable=False),
        sa.Column('api_key', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.Column('updated_by', sa.String(36), nullable=True),
        sa.UniqueConstraint('org_id', 'provider', name='uq_org_provider'),
    )
    op.create_index('ix_org_api_keys_org_id', 'org_api_keys', ['org_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_org_api_keys_org_id', table_name='org_api_keys')
    op.drop_table('org_api_keys')
