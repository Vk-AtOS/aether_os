"""Per-organisation LLM USD cap override and org-level kill switch (KAN-116).

Revision ID: org_llm_spend_controls
Revises: merge_a4_a7_heads
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'org_llm_spend_controls'
down_revision: Union[str, None] = 'merge_a4_a7_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('organisations') as b:
        b.add_column(sa.Column('llm_monthly_cap_usd', sa.Float(), nullable=True))
        b.add_column(sa.Column('llm_disabled', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('organisations') as b:
        b.drop_column('llm_disabled')
        b.drop_column('llm_monthly_cap_usd')
