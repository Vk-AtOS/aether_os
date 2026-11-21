"""Every correction is in its agent's eval set until a human removes it (KAN-25 owner decision).

Root cause: corrections only entered the eval set when an admin marked them "good example", so the
set stayed empty and the pass rate per agent never moved. New rows now default to True (the model);
this puts the existing ones in as well. Data only, no schema change.

Revision ID: prime_corrections_in_eval
Revises: hash_legacy_plaintext_tokens
Create Date: 2026-11-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'prime_corrections_in_eval'
down_revision: Union[str, None] = 'hash_legacy_plaintext_tokens'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "prime_corrections" in sa.inspect(op.get_bind()).get_table_names():
        op.execute(sa.text("UPDATE prime_corrections SET good_example = :t").bindparams(t=True))


def downgrade() -> None:
    pass   # the previous meaning (explicitly marked) cannot be rebuilt
