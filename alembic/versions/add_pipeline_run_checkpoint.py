"""add checkpoint_data to pipeline runs

Revision ID: add_pipeline_run_checkpoint
Revises: encrypt_sensitive_columns, add_org_scim_token
Create Date: 2026-06-03

Adds a nullable JSONB (PostgreSQL) / JSON (SQLite) column `checkpoint_data`
to the `runs` table.  This column stores:
  {
    "last_completed_phase": "p06_review_security",
    "accumulated_context": { ... }
  }
so a failed run can be resumed from the next unfinished phase without
restarting from p01.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_pipeline_run_checkpoint"
down_revision: Union[str, tuple] = "add_stripe_customer_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use JSONB on PostgreSQL for efficient partial indexing; fall back to JSON
    # for SQLite (used in dev / test environments).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        col_type = sa.dialects.postgresql.JSONB(astext_type=sa.Text())
    else:
        col_type = sa.JSON()

    op.add_column(
        "runs",
        sa.Column("checkpoint_data", col_type, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runs", "checkpoint_data")
