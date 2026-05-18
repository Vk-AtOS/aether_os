"""add user_id to runs table

Revision ID: revision_add_user_id_runs
Revises: revision_f7a8b9c0d1e2
Create Date: 2026-05-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision: str = 'revision_add_user_id_runs'
down_revision: str = 'revision_f7a8b9c0d1e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('runs', sa.Column('user_id', sa.String(255), nullable=True))
    op.create_index('ix_runs_user_id', 'runs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_runs_user_id', table_name='runs')
    op.drop_column('runs', 'user_id')
