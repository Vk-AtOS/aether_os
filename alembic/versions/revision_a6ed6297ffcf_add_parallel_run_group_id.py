"""add_parallel_run_group_id

Revision ID: revision_a6ed6297ffcf
Revises: revision_d26b82ffa45c
Create Date: 2026-05-05 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'revision_a6ed6297ffcf'
down_revision: Union[str, None] = 'revision_d26b82ffa45c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('runs', sa.Column('parallel_run_group_id', sa.String(length=36), nullable=True))

def downgrade() -> None:
    op.drop_column('runs', 'parallel_run_group_id')
