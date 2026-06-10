"""add index on events.timestamp for log query performance

Revision ID: revision_events_timestamp_idx
Revises: revision_merge_guardian_heads
Create Date: 2026-06-10

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'revision_events_timestamp_idx'
down_revision: Union[str, tuple] = 'revision_merge_guardian_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_events_timestamp', 'events', ['timestamp'])


def downgrade() -> None:
    op.drop_index('ix_events_timestamp', table_name='events')
