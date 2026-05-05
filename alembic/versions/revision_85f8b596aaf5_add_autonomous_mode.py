"""add_autonomous_mode_and_self_test_report

Revision ID: revision_85f8b596aaf5
Revises: ea230bec6fc8
Create Date: 2026-05-05 14:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'revision_85f8b596aaf5'
down_revision: Union[str, None] = 'ea230bec6fc8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Add autonomous_mode to organisations
    op.add_column('organisations', sa.Column('autonomous_mode', sa.Boolean(), server_default='0', nullable=False))
    
    # Add self_test_report to runs
    op.add_column('runs', sa.Column('self_test_report', sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column('organisations', 'autonomous_mode')
    op.drop_column('runs', 'self_test_report')
