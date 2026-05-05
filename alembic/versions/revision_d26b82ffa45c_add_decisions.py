"""add_decisions_and_org_settings

Revision ID: revision_d26b82ffa45c
Revises: ea230bec6fc8
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import uuid

revision: str = 'revision_d26b82ffa45c'
down_revision: Union[str, None] = 'ea230bec6fc8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Add decision_mode to organisations
    op.add_column('organisations', sa.Column('decision_mode', sa.String(length=20), server_default='auto', nullable=False))
    
    # Create decisions table
    op.create_table('decisions',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('decision_type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('what', sa.Text(), nullable=False),
        sa.Column('why', sa.Text(), nullable=False),
        sa.Column('alternatives', sa.Text(), nullable=False), # JSON
        sa.Column('impact', sa.Text(), nullable=False),
        sa.Column('phase', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('human_choice', sa.Text(), nullable=True),
        sa.Column('timeout_seconds', sa.Integer(), server_default='300', nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('decided_at', sa.Float(), nullable=True),
    )

def downgrade() -> None:
    op.drop_column('organisations', 'decision_mode')
    op.drop_table('decisions')
