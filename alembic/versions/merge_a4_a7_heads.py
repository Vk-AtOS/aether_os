"""Merge the two migration heads created by parallel work (A4 budget/audit changes, A7 hot indexes).

Root cause: both branches added a revision on top of per_org_ledger_chains, which leaves two heads and makes
`alembic upgrade head` refuse to run. This revision changes no schema.

Revision ID: merge_a4_a7_heads
Revises: add_hot_filter_indexes, audit_log_resource_id_wider
Create Date: 2026-11-15
"""
from typing import Sequence, Union

revision: str = 'merge_a4_a7_heads'
down_revision: Union[str, Sequence[str], None] = ('add_hot_filter_indexes', 'audit_log_resource_id_wider')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
