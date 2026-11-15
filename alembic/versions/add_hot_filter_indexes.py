"""Composite indexes for the hot per-organisation filters (KAN-131 / KAN-136).

Root cause: list endpoints filter by org_id plus status/started_at (runs), unread (notifications),
run (artifact_embeddings) and published (marketplace_profiles), but only single-column indexes
existed, so each request scanned every row of the organisation (or table) as it grew.

IF NOT EXISTS keeps this idempotent for databases that init_db already indexed.

Revision ID: add_hot_filter_indexes
Revises: per_org_ledger_chains
Create Date: 2026-11-14
"""
from typing import Sequence, Union

from alembic import op

try:   # one definition shared with the empty-database bootstrap (core/schema_ddl.py)
    from aether_os.core import schema_ddl
except ModuleNotFoundError:   # alembic run from the repository root without PYTHONPATH (alembic.ini prepends ".")
    from core import schema_ddl

revision: str = 'add_hot_filter_indexes'
down_revision: Union[str, None] = 'per_org_ledger_chains'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = ("ix_runs_org_status", "ix_runs_org_started_at", "ix_notifications_org_user_unread",
           "ix_artifact_embeddings_org_run", "ix_marketplace_profiles_org", "ix_marketplace_profiles_published")


def upgrade() -> None:
    schema_ddl.apply(op.get_bind(), only=INDEXES)


def downgrade() -> None:
    for name in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
