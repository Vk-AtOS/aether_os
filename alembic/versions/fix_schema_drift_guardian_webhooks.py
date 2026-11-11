"""Close schema drift between the ORM models and migrated databases.

Root cause: these objects were only ever created by Base.metadata.create_all on
a fresh database. create_all never adds a column to an existing table, and the
guardian models are not imported at startup, so a migrated database lacked:
  - guardian_events, guardian_snapshots      (Guardian pages returned 500)
  - webhooks.secret_hash                     (GET /webhooks returned 500)
  - global_patterns.org_id

Revision ID: fix_schema_drift_guardian_webhooks
Revises: add_audit_chain_prime_delegations
Create Date: 2026-11-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'fix_schema_drift_guardian_webhooks'
down_revision: Union[str, None] = 'add_audit_chain_prime_delegations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    # A fresh database made by create_all already has these; only add what is missing.
    if "guardian_events" not in existing:
        op.create_table(
            "guardian_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("event_type", sa.String(50), nullable=False, index=True),
            sa.Column("severity", sa.String(20), nullable=False, index=True),
            sa.Column("source_ip", sa.String(64), nullable=True),
            sa.Column("endpoint", sa.String(512), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.Column("org_id", sa.String(50), nullable=True, index=True),
            sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "guardian_snapshots" not in existing:
        op.create_table(
            "guardian_snapshots",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("snapshot_path", sa.Text(), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("integrity_hash", sa.String(64), nullable=False),
            sa.Column("trigger", sa.String(30), nullable=False, server_default="scheduled"),
            sa.Column("status", sa.String(20), nullable=False, server_default="ok"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("db_backend", sa.String(20), nullable=False, server_default="sqlite"),
        )
    op.execute("ALTER TABLE webhooks ADD COLUMN IF NOT EXISTS secret_hash VARCHAR(255)")
    op.execute("ALTER TABLE global_patterns ADD COLUMN IF NOT EXISTS org_id VARCHAR(50) "
               "REFERENCES organisations(id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_global_patterns_org_id ON global_patterns (org_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_global_patterns_org_id")
    op.execute("ALTER TABLE global_patterns DROP COLUMN IF EXISTS org_id")
    op.execute("ALTER TABLE webhooks DROP COLUMN IF EXISTS secret_hash")
    op.execute("DROP TABLE IF EXISTS guardian_snapshots")
    op.execute("DROP TABLE IF EXISTS guardian_events")
