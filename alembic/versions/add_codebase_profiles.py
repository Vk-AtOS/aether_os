"""add codebase_profiles table

Revision ID: add_codebase_profiles
Revises: add_org_scim_token
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_codebase_profiles'
down_revision = 'add_org_scim_token'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'codebase_profiles',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(36), sa.ForeignKey('organisations.id'), nullable=False),
        sa.Column('repo_url', sa.String(512), nullable=False),
        sa.Column('repo_name', sa.String(256), nullable=False),
        sa.Column('detected_stack', sa.JSON, nullable=True),
        sa.Column('file_tree', sa.JSON, nullable=True),
        sa.Column('summary', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_codebase_profiles_org_id', 'codebase_profiles', ['org_id'])


def downgrade():
    op.drop_index('ix_codebase_profiles_org_id', table_name='codebase_profiles')
    op.drop_table('codebase_profiles')
