"""add branch run columns to runs table

Revision ID: revision_f7a8b9c0d1e2
Revises: revision_e1f2a3b4c5d6
Create Date: 2026-05-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision: str = 'revision_f7a8b9c0d1e2'
down_revision: str = 'cda442e061e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('runs', sa.Column('parent_run_id', sa.String(36), nullable=True))
    op.add_column('runs', sa.Column('branch_phase', sa.String(100), nullable=True))
    op.create_index('ix_runs_parent_run_id', 'runs', ['parent_run_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_runs_parent_run_id', table_name='runs')
    op.drop_column('runs', 'branch_phase')
    op.drop_column('runs', 'parent_run_id')
