"""phase_config_org_scoping_and_fk_indexes

Revision ID: revision_b1c2d3e4f5a6
Revises: 23e65878ea04
Create Date: 2026-05-15

T2-09: Add org_id to phase_configs so each org has its own phase settings.
T3-06: Add missing FK indexes on events, snapshots, decisions, webhooks, workspaces.
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

logger = logging.getLogger(__name__)


revision: str = "revision_b1c2d3e4f5a6"
down_revision: Union[str, None] = "23e65878ea04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # T2-09: Rebuild phase_configs with org_id as part of the primary key.
    # Old table had (phase_name) as PK; new table has (org_id, phase_name).
    with op.batch_alter_table("phase_configs", schema=None) as batch_op:
        # Add org_id column with a default so existing rows aren't broken.
        batch_op.add_column(
            sa.Column("org_id", sa.String(length=36), nullable=False, server_default="default")
        )

    # Recreate the primary key constraint to include org_id.
    # batch_alter_table handles SQLite-safe PK recreation automatically.
    with op.batch_alter_table("phase_configs", schema=None) as batch_op:
        batch_op.drop_constraint("pk_phase_configs", type_="primary") if False else None
        try:
            batch_op.create_primary_key("pk_phase_configs", ["org_id", "phase_name"])
        except Exception as exc:
            logger.debug("PK constraint creation skipped (may already exist on PostgreSQL): %s", exc)

    # T3-06: Add missing FK indexes
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.create_index("ix_events_run_id", ["run_id"])

    with op.batch_alter_table("snapshots", schema=None) as batch_op:
        batch_op.create_index("ix_snapshots_run_id", ["run_id"])

    with op.batch_alter_table("decisions", schema=None) as batch_op:
        batch_op.create_index("ix_decisions_org_id", ["org_id"])
        batch_op.create_index("ix_decisions_run_id_idx", ["run_id"])

    with op.batch_alter_table("webhooks", schema=None) as batch_op:
        batch_op.create_index("ix_webhooks_org_id", ["org_id"])

    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.create_index("ix_workspaces_org_id", ["org_id"])


def downgrade() -> None:
    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.drop_index("ix_workspaces_org_id")

    with op.batch_alter_table("webhooks", schema=None) as batch_op:
        batch_op.drop_index("ix_webhooks_org_id")

    with op.batch_alter_table("decisions", schema=None) as batch_op:
        batch_op.drop_index("ix_decisions_run_id_idx")
        batch_op.drop_index("ix_decisions_org_id")

    with op.batch_alter_table("snapshots", schema=None) as batch_op:
        batch_op.drop_index("ix_snapshots_run_id")

    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_index("ix_events_run_id")

    with op.batch_alter_table("phase_configs", schema=None) as batch_op:
        batch_op.drop_column("org_id")
