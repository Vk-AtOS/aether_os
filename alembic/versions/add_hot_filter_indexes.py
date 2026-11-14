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

revision: str = 'add_hot_filter_indexes'
down_revision: Union[str, None] = 'per_org_ledger_chains'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = {
    "ix_runs_org_status": "runs(org_id, status)",
    "ix_runs_org_started_at": "runs(org_id, started_at)",
    "ix_notifications_org_user_unread": "notifications(org_id, user_id, is_read)",
    "ix_artifact_embeddings_org_run": "artifact_embeddings(org_id, run_id)",
    "ix_marketplace_profiles_org": "marketplace_profiles(org_id)",
    "ix_marketplace_profiles_published": "marketplace_profiles(is_published, created_at)",
}


def upgrade() -> None:
    for name, target in INDEXES.items():
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")


def downgrade() -> None:
    for name in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
