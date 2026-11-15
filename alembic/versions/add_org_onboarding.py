"""org_onboarding: one row per organisation that hid the onboarding banner (KAN-165).

Revision ID: add_org_onboarding
Revises: add_notification_prefs
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'add_org_onboarding'
down_revision: Union[str, None] = 'add_notification_prefs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'org_onboarding',
        sa.Column('org_id', sa.String(50), primary_key=True),
        sa.Column('dismissed_by', sa.String(36), nullable=False),
        sa.Column('dismissed_at', sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table('org_onboarding')
