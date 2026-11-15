"""Organisation setting: require MFA for owners/admins, with a grace period (KAN-186).

Revision ID: admin_mfa_policy
Revises: org_llm_spend_controls
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'admin_mfa_policy'
down_revision: Union[str, None] = 'org_llm_spend_controls'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('organisations') as b:
        b.add_column(sa.Column('require_admin_mfa', sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column('admin_mfa_grace_until', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('organisations') as b:
        b.drop_column('admin_mfa_grace_until')
        b.drop_column('require_admin_mfa')
