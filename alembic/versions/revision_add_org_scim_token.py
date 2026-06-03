"""add scim_token to organisations

Revision ID: add_org_scim_token
Revises: revision_merge_guardian_heads
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_org_scim_token'
down_revision = 'revision_merge_guardian_heads'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'organisations',
        sa.Column('scim_token', sa.String(128), nullable=True),
    )


def downgrade():
    op.drop_column('organisations', 'scim_token')
