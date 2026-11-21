"""Org-chosen LLM USD cap, separate from the platform-set one (KAN-116).

Revision ID: org_llm_org_cap
Revises: hash_legacy_plaintext_tokens
Create Date: 2026-11-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'org_llm_org_cap'
down_revision: Union[str, None] = 'hash_legacy_plaintext_tokens'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('organisations') as b:
        b.add_column(sa.Column('llm_org_cap_usd', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('organisations') as b:
        b.drop_column('llm_org_cap_usd')
