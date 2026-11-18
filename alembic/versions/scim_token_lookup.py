"""Indexed digest of the SCIM token so authentication is one lookup, not a bcrypt per organisation (KAN-163/136).

Existing tokens keep working through the legacy scan until they are rotated.

Revision ID: scim_token_lookup
Revises: scim_groups
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'scim_token_lookup'
down_revision: Union[str, None] = 'scim_groups'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('organisations') as b:
        b.add_column(sa.Column('scim_token_lookup', sa.String(64), nullable=True))
        b.create_index('ix_organisations_scim_token_lookup', ['scim_token_lookup'])


def downgrade() -> None:
    with op.batch_alter_table('organisations') as b:
        b.drop_index('ix_organisations_scim_token_lookup')
        b.drop_column('scim_token_lookup')
