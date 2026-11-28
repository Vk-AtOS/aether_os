"""Per-organisation monthly LLM token cap (KAN-261).

Root cause: the token cap came only from the plan table, so an org could not be given room for more builds than its plan
default without changing every org on the plan. NULL keeps the plan's cap.

Revision ID: org_llm_token_cap
Revises: org_require_human_review
Create Date: 2026-11-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'org_llm_token_cap'
down_revision: Union[str, None] = 'org_require_human_review'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('organisations') as b:
        b.add_column(sa.Column('llm_monthly_token_cap', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('organisations') as b:
        b.drop_column('llm_monthly_token_cap')
