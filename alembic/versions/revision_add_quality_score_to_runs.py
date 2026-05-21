"""add quality_score to runs table

Revision ID: revision_add_quality_score_runs
Revises: revision_add_user_id_runs
Create Date: 2026-05-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision: str = 'revision_add_quality_score_runs'
down_revision: str = 'revision_add_user_id_runs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('runs', sa.Column('quality_score', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('runs', 'quality_score')
