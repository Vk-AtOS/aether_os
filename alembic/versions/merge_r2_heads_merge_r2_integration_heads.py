"""merge r2 integration heads

Revision ID: merge_r2_heads
Revises: add_org_onboarding, add_prime_corrections, pgvector_backfill_and_index, scim_token_lookup
Create Date: 2026-11-15 21:55:13.256216

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'merge_r2_heads'
down_revision: Union[str, None] = ('add_org_onboarding', 'add_prime_corrections', 'pgvector_backfill_and_index', 'scim_token_lookup')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
