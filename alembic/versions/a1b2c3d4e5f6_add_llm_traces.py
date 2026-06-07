"""add llm_traces table

Revision ID: a1b2c3d4e5f6
Revises: revision_merge_guardian_heads
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'revision_merge_guardian_heads'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'llm_traces',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('phase', sa.String(50), nullable=False, index=True),
        sa.Column('task_type', sa.String(100), nullable=True),
        sa.Column('model', sa.String(100), nullable=True),
        sa.Column('prompt', sa.Text(), nullable=True),
        sa.Column('raw_response', sa.Text(), nullable=True),
        sa.Column('parsed_ok', sa.Boolean(), server_default='true'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('attempt', sa.Integer(), server_default='1'),
        sa.Column('duration_ms', sa.Integer(), server_default='0'),
        sa.Column('tokens_in', sa.Integer(), server_default='0'),
        sa.Column('tokens_out', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True, index=True),
    )


def downgrade():
    op.drop_table('llm_traces')
