"""org_dpa_acceptance: who accepted which DPA version for an organisation, and when (KAN-165).

Revision ID: add_org_dpa_acceptance
Revises: add_webhook_outbox_quiet_hours
Create Date: 2026-11-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'add_org_dpa_acceptance'
down_revision: Union[str, None] = 'add_webhook_outbox_quiet_hours'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'org_dpa_acceptance',
        sa.Column('org_id', sa.String(50), primary_key=True),
        sa.Column('version', sa.String(20), primary_key=True),
        sa.Column('accepted_by', sa.String(36), nullable=False),
        sa.Column('accepted_at', sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table('org_dpa_acceptance')
