"""token_budget_records: one row per (org, month).

Root cause: the row was created with select-then-insert and no unique constraint, so two
concurrent first calls of a month inserted two rows; every later read raised
MultipleResultsFound and the spend cap saw only one of the rows. Existing duplicates are
merged into the oldest row before the constraint is added.

Revision ID: token_budget_unique_org_month
Revises: per_org_ledger_chains
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'token_budget_unique_org_month'
down_revision: Union[str, None] = 'per_org_ledger_chains'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SUMMED = ("input_tokens", "output_tokens", "runs", "cache_hits", "cache_misses", "estimated_cost_usd")


def upgrade() -> None:
    t = "token_budget_records"
    for col in _SUMMED:
        op.execute(
            f"UPDATE {t} SET {col} = (SELECT SUM(b.{col}) FROM {t} b "
            f"WHERE b.org_id = {t}.org_id AND b.month = {t}.month) "
            f"WHERE id IN (SELECT MIN(id) FROM {t} GROUP BY org_id, month HAVING COUNT(*) > 1)"
        )
    op.execute(f"DELETE FROM {t} WHERE id NOT IN (SELECT MIN(id) FROM {t} GROUP BY org_id, month)")
    with op.batch_alter_table(t) as batch:
        batch.create_unique_constraint("uq_token_budget_org_month", ["org_id", "month"])


def downgrade() -> None:
    with op.batch_alter_table("token_budget_records") as batch:
        batch.drop_constraint("uq_token_budget_org_month", type_="unique")
