"""Organisation setting: require human review at every approval gate, whatever a request asks (KAN-248).

Revision ID: org_require_human_review
Revises: prime_learning_loop
Create Date: 2026-11-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'org_require_human_review'
down_revision: Union[str, None] = 'prime_learning_loop'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('organisations') as b:
        b.add_column(sa.Column('require_human_review', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('organisations') as b:
        b.drop_column('require_human_review')
