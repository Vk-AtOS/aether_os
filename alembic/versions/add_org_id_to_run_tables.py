"""org_id on the eight run-owned tables (KAN-131)

Root cause: events, snapshots, run_specs, pipeline_events, llm_traces, questionnaire_sessions,
phase_completions and run_metadata carried only run_id, so every per-organisation query, every
retention job and any row-level security had to join runs. org_id is added (nullable: rows written
by raw SQL stay valid), back-filled from runs.org_id, and indexed. New rows get it from the ORM
(core.models._fill_org_id_from_run).

Revision ID: add_org_id_to_run_tables
Revises: merge_r2_heads
Create Date: 2026-11-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'add_org_id_to_run_tables'
down_revision: Union[str, None] = 'merge_r2_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("events", "snapshots", "run_specs", "pipeline_events", "llm_traces",
          "questionnaire_sessions", "phase_completions", "run_metadata")


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for table in TABLES:
        if table not in insp.get_table_names():
            continue
        if "org_id" not in {c["name"] for c in insp.get_columns(table)}:
            op.add_column(table, sa.Column("org_id", sa.String(50), nullable=True))
        op.execute(
            f"UPDATE {table} SET org_id = (SELECT runs.org_id FROM runs WHERE runs.id = {table}.run_id) "
            f"WHERE org_id IS NULL"
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_org_id ON {table} (org_id)")


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for table in TABLES:
        if table in insp.get_table_names() and "org_id" in {c["name"] for c in insp.get_columns(table)}:
            op.execute(f"DROP INDEX IF EXISTS ix_{table}_org_id")
            op.drop_column(table, "org_id")
