"""add must_change_password to users (SEC-H1/FIX-15)

Revision ID: add_must_change_password
Revises: revision_merge_guardian_heads
Create Date: 2026-07-17 00:00:00.000000

Forces a password change after admin reset or invite so plaintext temp
credentials have a short TTL and are never reusable.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_must_change_password'
down_revision: Union[str, None] = 'revision_merge_guardian_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')
