"""add learning_clarifications_pending table

Revision ID: add_learning_clarifications
Revises: add_golden_builds_feedback
Create Date: 2026-06-05
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "add_learning_clarifications"
down_revision = "add_golden_builds_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_clarifications_pending",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False, index=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("question_type", sa.String(32), nullable=False, server_default="clarification"),
        sa.Column("context", sa.JSON, nullable=True),
        sa.Column("answered_at", sa.DateTime, nullable=True),
        sa.Column("answer", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("learning_clarifications_pending")
