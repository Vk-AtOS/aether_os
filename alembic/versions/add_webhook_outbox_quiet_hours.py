"""webhook_outbox (durable webhook retry, KAN-102) and notification_quiet_hours (KAN-159).

Revision ID: add_webhook_outbox_quiet_hours
Revises: merge_r3_heads
Create Date: 2026-11-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'add_webhook_outbox_quiet_hours'
down_revision: Union[str, None] = 'merge_r3_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'webhook_outbox',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(50), nullable=False, index=True),
        sa.Column('webhook_id', sa.String(36), nullable=False),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('delivery_id', sa.String(36), nullable=False),
        sa.Column('payload', sa.JSON, nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer, nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.Float, nullable=False),
        sa.Column('last_error', sa.String(500), nullable=True),
        sa.Column('created_at', sa.Float, nullable=False),
        sa.Column('updated_at', sa.Float, nullable=False),
    )
    op.create_index('ix_webhook_outbox_due', 'webhook_outbox', ['status', 'next_attempt_at'])
    op.create_table(
        'notification_quiet_hours',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(50), nullable=False, index=True),
        sa.Column('user_id', sa.String(36), nullable=False, server_default=''),
        sa.Column('start_minute', sa.Integer, nullable=False),
        sa.Column('end_minute', sa.Integer, nullable=False),
        sa.Column('tz', sa.String(64), nullable=False, server_default='UTC'),
        sa.UniqueConstraint('org_id', 'user_id', name='uq_notification_quiet_hours'),
    )


def downgrade() -> None:
    op.drop_table('notification_quiet_hours')
    op.drop_index('ix_webhook_outbox_due', table_name='webhook_outbox')
    op.drop_table('webhook_outbox')
