"""add_guardian_events_and_snapshots

Revision ID: revision_guardian_module
Revises: merge_heads_final
Create Date: 2026-05-30 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'revision_guardian_module'
down_revision: Union[str, None] = 'merge_heads_final'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'guardian_events',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('event_type', sa.String(length=50), nullable=False, index=True),
        sa.Column('severity', sa.String(length=20), nullable=False, index=True),
        sa.Column('source_ip', sa.String(length=64), nullable=True),
        sa.Column('endpoint', sa.String(length=512), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=True),
        sa.Column('resolved', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_guardian_events_created_at', 'guardian_events', ['created_at'])

    op.create_table(
        'guardian_snapshots',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('snapshot_path', sa.Text(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), server_default='0', nullable=False),
        sa.Column('integrity_hash', sa.String(length=64), nullable=False),
        sa.Column('trigger', sa.String(length=30), server_default='scheduled', nullable=False),
        sa.Column('status', sa.String(length=20), server_default='ok', nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('db_backend', sa.String(length=20), server_default='sqlite', nullable=False),
    )
    op.create_index('ix_guardian_snapshots_created_at', 'guardian_snapshots', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_guardian_snapshots_created_at', 'guardian_snapshots')
    op.drop_table('guardian_snapshots')
    op.drop_index('ix_guardian_events_created_at', 'guardian_events')
    op.drop_table('guardian_events')
