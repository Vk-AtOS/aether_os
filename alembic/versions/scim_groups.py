"""SCIM groups and their members (KAN-163).

Revision ID: scim_groups
Revises: admin_mfa_policy
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'scim_groups'
down_revision: Union[str, None] = 'admin_mfa_policy'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scim_groups',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(50), nullable=False, index=True),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('org_id', 'display_name', name='uq_scim_group_org_name'),
    )
    op.create_table(
        'scim_group_members',
        sa.Column('group_id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), primary_key=True, index=True),
        sa.Column('org_id', sa.String(50), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table('scim_group_members')
    op.drop_table('scim_groups')
