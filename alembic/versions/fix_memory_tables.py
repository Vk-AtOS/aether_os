"""fix_memory and run_pattern_memory: structured, org-scoped memory of runs (KAN-215).

Root cause: the same repair (missing UI primitive, case-mismatched import) cost a model call on every run because
nothing stored which fix worked for which normalised error signature.

Revision ID: fix_memory_tables
Revises: prime_corrections_in_eval
Create Date: 2026-11-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'fix_memory_tables'
down_revision: Union[str, None] = 'prime_corrections_in_eval'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fix_memory',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(50), nullable=False),
        sa.Column('signature', sa.String(64), nullable=False),
        sa.Column('file_kind', sa.String(64), nullable=False, server_default=''),
        sa.Column('patches', sa.JSON(), nullable=False),
        sa.Column('hits', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('run_id', sa.String(36), nullable=True),
        sa.Column('user_id', sa.String(36), nullable=False, server_default='system'),
        sa.Column('failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('org_id', 'signature', name='uq_fix_memory_org_signature'),
    )
    op.create_index('ix_fix_memory_org_id', 'fix_memory', ['org_id'])
    op.create_index('ix_fix_memory_run_id', 'fix_memory', ['run_id'])
    op.create_table(
        'run_pattern_memory',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(50), nullable=False),
        sa.Column('run_id', sa.String(36), nullable=False),
        sa.Column('domain', sa.String(255), nullable=False, server_default=''),
        sa.Column('entities', sa.JSON(), nullable=False),
        sa.Column('patterns', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('org_id', 'run_id', name='uq_run_pattern_memory_org_run'),
    )
    op.create_index('ix_run_pattern_memory_org_id', 'run_pattern_memory', ['org_id'])
    op.create_index('ix_run_pattern_memory_domain', 'run_pattern_memory', ['domain'])


def downgrade() -> None:
    op.drop_table('run_pattern_memory')
    op.drop_table('fix_memory')
