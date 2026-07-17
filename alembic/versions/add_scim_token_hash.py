"""add scim_token_hash to organisations (DB-H1)

Revision ID: add_scim_token_hash
Revises: add_must_change_password
Create Date: 2026-07-17 00:00:01.000000

SCIM provisioning tokens were stored verbatim. A DB dump exposed every org's
token. The hash column stores a bcrypt digest; the plaintext column is kept for
the migration window and nulled out when an org rotates via /settings/scim/rotate.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_scim_token_hash'
down_revision: Union[str, None] = 'add_must_change_password'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'organisations',
        sa.Column('scim_token_hash', sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('organisations', 'scim_token_hash')
