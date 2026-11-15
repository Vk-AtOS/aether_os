"""notification_prefs: per-user and per-org notification settings (KAN-159).

Revision ID: add_notification_prefs
Revises: add_decisions_org_status_index
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'add_notification_prefs'
down_revision: Union[str, None] = 'add_decisions_org_status_index'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notification_prefs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(50), nullable=False, index=True),
        sa.Column('user_id', sa.String(36), nullable=False, server_default=''),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('in_app', sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column('email', sa.Boolean, nullable=False, server_default=sa.true()),
        sa.UniqueConstraint('org_id', 'user_id', 'event_type', name='uq_notification_prefs'),
    )


def downgrade() -> None:
    op.drop_table('notification_prefs')
