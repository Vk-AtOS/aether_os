"""Unique keys for installed_plugins, user_learning_patterns, build_feedback, golden_builds (KAN-131).

Root cause: each of these was written with select-then-insert and no unique constraint, so two
concurrent first writes created two rows; later reads then raised MultipleResultsFound or counted
a rating twice. Existing duplicates are removed (oldest row kept) before the constraints are added.

Revision ID: unique_keys_plugins_learning_feedback_golden
Revises: merge_a4_a7_heads
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'unique_keys_plugins_learning_feedback_golden'
down_revision: Union[str, None] = 'merge_a4_a7_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# table -> (constraint name, key columns)
_KEYS = {
    "installed_plugins": ("uq_installed_plugin_org_plugin", ["org_id", "plugin_id"]),
    "user_learning_patterns": ("uq_learning_pattern_key", ["org_id", "user_id", "pattern_type", "pattern_key"]),
    "build_feedback": ("uq_build_feedback_run_user", ["run_id", "user_id"]),
    "golden_builds": ("uq_golden_build_run", ["run_id"]),
}


def upgrade() -> None:
    for table, (name, cols) in _KEYS.items():
        key = ", ".join(cols)
        # NULL key parts never conflict, so rows with a NULL (build_feedback.user_id) are kept as they are.
        not_null = " AND ".join(f"{c} IS NOT NULL" for c in cols)
        op.execute(
            f"DELETE FROM {table} WHERE {not_null} AND id NOT IN "
            f"(SELECT MIN(id) FROM {table} WHERE {not_null} GROUP BY {key})"
        )
        with op.batch_alter_table(table) as batch:
            batch.create_unique_constraint(name, cols)


def downgrade() -> None:
    for table, (name, _cols) in _KEYS.items():
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="unique")
