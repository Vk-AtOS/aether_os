"""Index for the org-wide pending-decisions inbox (KAN-162).

Root cause: decisions had single-column indexes on run_id and org_id only; the inbox filters by org and
status and sorts by created_at, which would scan every decision of the organisation as it grows.
IF NOT EXISTS keeps this idempotent where init_db already created it.

Revision ID: add_decisions_org_status_index
Revises: merge_a4_a7_heads
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op

try:   # one definition shared with the empty-database bootstrap (core/schema_ddl.py)
    from aether_os.core import schema_ddl
except ModuleNotFoundError:   # alembic run from the repository root without PYTHONPATH (alembic.ini prepends ".")
    from core import schema_ddl

revision: str = 'add_decisions_org_status_index'
down_revision: Union[str, None] = 'merge_a4_a7_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    schema_ddl.apply(op.get_bind(), only=("ix_decisions_org_status_created",))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_decisions_org_status_created")
